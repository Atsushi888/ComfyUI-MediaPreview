# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import time
import uuid
from typing import Optional

import numpy as np
from PIL import Image
import torch

import folder_paths

from .server import register_routes, set_preview_path


_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv", ".avi"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_MEDIA_EXTS = _VIDEO_EXTS | _IMAGE_EXTS


def _norm(p: str) -> str:
    return os.path.normpath((p or "").strip()).replace("\\", "/")


def _is_media_file(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext in _MEDIA_EXTS


def _is_image_file(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext in _IMAGE_EXTS


def _is_valid_filename(name: str) -> bool:
    if not name:
        return False
    if name.startswith(".") or name.startswith("._"):
        return False
    ext = os.path.splitext(name)[1].lower()
    return ext in _MEDIA_EXTS


def _pick_best_file(base_dir: str) -> str:
    """
    base_dir 配下の候補から、動画優先で1本返す。
    なければ画像。
    """
    if not base_dir or not os.path.isdir(base_dir):
        return ""

    try:
        files = [f for f in os.listdir(base_dir) if _is_valid_filename(f)]
    except Exception:
        return ""

    if not files:
        return ""

    files = sorted(files)

    for f in files:
        if os.path.splitext(f)[1].lower() in _VIDEO_EXTS:
            return _norm(os.path.join(base_dir, f))

    for f in files:
        if os.path.splitext(f)[1].lower() in _IMAGE_EXTS:
            return _norm(os.path.join(base_dir, f))

    return ""


def _tensor_to_numpy(x):
    if x is None:
        return None
    try:
        if hasattr(x, "detach"):
            x = x.detach()
        if hasattr(x, "cpu"):
            x = x.cpu()
        if hasattr(x, "numpy"):
            x = x.numpy()
    except Exception:
        pass
    return x


def _make_empty_image(h: int = 64, w: int = 64):
    arr = np.zeros((1, h, w, 3), dtype=np.float32)
    return torch.from_numpy(arr)


def _make_empty_mask(h: int = 64, w: int = 64):
    arr = np.zeros((1, h, w), dtype=np.float32)
    return torch.from_numpy(arr)


def _load_image_as_tensor(path: str):
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            arr = np.asarray(im).astype(np.float32) / 255.0
            arr = arr[None, ...]  # [1,H,W,C]
            return torch.from_numpy(arr)
    except Exception as e:
        print(f"[MediaPreview] image load failed: {e}")
        return _make_empty_image()


def _load_mask_from_image(path: str):
    try:
        with Image.open(path) as im:
            im = im.convert("L")
            arr = np.asarray(im).astype(np.float32) / 255.0
            arr = arr[None, ...]  # [1,H,W]
            return torch.from_numpy(arr)
    except Exception as e:
        print(f"[MediaPreview] mask load failed: {e}")
        return _make_empty_mask()


def _save_image_tensor_to_temp_path(image_tensor) -> str:
    """
    ComfyUI IMAGE:
      通常 [B,H,W,C] float 0..1
    これを temp 配下に PNG 保存して path を返す
    """
    try:
        arr = _tensor_to_numpy(image_tensor)
        if arr is None:
            return ""

        arr = np.asarray(arr)

        if arr.ndim == 4:
            arr = arr[0]
        elif arr.ndim != 3:
            print(f"[MediaPreview] unsupported image ndim={arr.ndim}")
            return ""

        if arr.shape[-1] != 3:
            print(f"[MediaPreview] unsupported image shape={arr.shape}")
            return ""

        if arr.dtype != np.uint8:
            arr = np.clip(arr * 255.0, 0, 255).astype(np.uint8)

        out_dir = folder_paths.get_temp_directory()
        os.makedirs(out_dir, exist_ok=True)

        filename = f"media_preview_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.png"
        out_path = os.path.join(out_dir, filename)

        Image.fromarray(arr).save(out_path)
        return _norm(out_path)

    except Exception as e:
        print(f"[MediaPreview] image temp save failed: {e}")
        return ""


def _save_mask_tensor_to_temp_path(mask_tensor) -> str:
    """
    ComfyUI MASK:
      通常 [B,H,W] または [H,W] float 0..1
    これを可視化用にRGB PNG保存
    """
    try:
        arr = _tensor_to_numpy(mask_tensor)
        if arr is None:
            return ""

        arr = np.asarray(arr)

        if arr.ndim == 3:
            arr = arr[0]
        elif arr.ndim != 2:
            print(f"[MediaPreview] unsupported mask ndim={arr.ndim}")
            return ""

        if arr.dtype != np.uint8:
            arr = np.clip(arr * 255.0, 0, 255).astype(np.uint8)

        rgb = np.stack([arr, arr, arr], axis=-1)

        out_dir = folder_paths.get_temp_directory()
        os.makedirs(out_dir, exist_ok=True)

        filename = f"media_preview_mask_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.png"
        out_path = os.path.join(out_dir, filename)

        Image.fromarray(rgb).save(out_path)
        return _norm(out_path)

    except Exception as e:
        print(f"[MediaPreview] mask temp save failed: {e}")
        return ""


class MediaPreview:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "base_dir": ("STRING", {"default": "/workspace/ComfyUI/output/"}),
                "media": ("STRING", {"default": "", "multiline": False}),
                "loop": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "media_path": ("STRING", {"default": "", "forceInput": True}),
                "image": ("IMAGE", {"forceInput": True}),
                "mask": ("MASK", {"forceInput": True}),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = ("STRING", "IMAGE", "MASK")
    RETURN_NAMES = ("media_path", "image", "mask")
    FUNCTION = "run"
    CATEGORY = "utils"
    OUTPUT_NODE = True

    def run(
        self,
        base_dir,
        media,
        loop,
        media_path="",
        image=None,
        mask=None,
        unique_id: Optional[str] = None,
    ):
        print("========== [MediaPreview.run] ==========")
        print(f"[MediaPreview.run] unique_id={unique_id!r}")
        print(f"[MediaPreview.run] base_dir={base_dir!r}")
        print(f"[MediaPreview.run] media={media!r}")
        print(f"[MediaPreview.run] media_path(raw)={media_path!r}")
        print(f"[MediaPreview.run] image is None? {image is None}")
        print(f"[MediaPreview.run] mask is None? {mask is None}")

        if image is not None:
            try:
                print(f"[MediaPreview.run] image type={type(image)}")
                print(f"[MediaPreview.run] image shape={getattr(image, 'shape', None)}")
            except Exception as e:
                print(f"[MediaPreview.run] image inspect error={e}")

        if mask is not None:
            try:
                print(f"[MediaPreview.run] mask type={type(mask)}")
                print(f"[MediaPreview.run] mask shape={getattr(mask, 'shape', None)}")
            except Exception as e:
                print(f"[MediaPreview.run] mask inspect error={e}")

        path = ""

        # 1) media_path 最優先
        mp = (media_path or "").strip()
        if mp:
            mp = _norm(mp)
            if _is_media_file(mp):
                path = mp

        # 2) media が明示されている場合だけ base_dir + media
        if not path:
            base = (base_dir or "").strip()
            med = (media or "").strip()
            if base and med:
                p = _norm(os.path.join(base, med))
                if _is_media_file(p):
                    path = p

        # 3) image fallback
        if not path and image is not None:
            path = _save_image_tensor_to_temp_path(image)
            print(f"[MediaPreview.run] image fallback path={path!r}")

        # 4) mask fallback
        if not path and mask is not None:
            path = _save_mask_tensor_to_temp_path(mask)
            print(f"[MediaPreview.run] mask fallback path={path!r}")

        # 5) 最後にだけ base_dir の best file
        if not path:
            base = (base_dir or "").strip()
            if base:
                path = _pick_best_file(base)

        print(f"[MediaPreview.run] resolved={path!r}")

        set_preview_path(unique_id, path)

        # image output
        if image is not None:
            out_image = image
        elif path and _is_image_file(path):
            out_image = _load_image_as_tensor(path)
        else:
            out_image = _make_empty_image()

        # mask output
        if mask is not None:
            out_mask = mask
        elif path and _is_image_file(path):
            out_mask = _load_mask_from_image(path)
        else:
            out_mask = _make_empty_mask()

        return (path, out_image, out_mask)


try:
    register_routes()
except Exception as e:
    print("[MediaPreview] route register failed at import:", e)