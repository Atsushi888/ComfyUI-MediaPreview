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


def _realpath(p: str) -> str:
    try:
        return os.path.realpath(os.path.abspath(os.path.expanduser((p or "").strip()))).replace("\\", "/")
    except Exception:
        return _norm(p)


def _resolve_local_file(path: str) -> str:
    p = _realpath(path)
    if not p:
        return ""
    if os.path.isfile(p) and _is_media_file(p):
        return p
    return ""


def _is_url(path: str) -> bool:
    s = (path or "").strip().lower()
    return s.startswith("http://") or s.startswith("https://")


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
            arr = arr[None, ...]
            return torch.from_numpy(arr)
    except Exception as e:
        print(f"[MediaPreview] image load failed: {e}")
        return _make_empty_image()


def _load_mask_from_image(path: str):
    try:
        with Image.open(path) as im:
            im = im.convert("L")
            arr = np.asarray(im).astype(np.float32) / 255.0
            arr = arr[None, ...]
            return torch.from_numpy(arr)
    except Exception as e:
        print(f"[MediaPreview] mask load failed: {e}")
        return _make_empty_mask()


def _save_image_tensor_to_temp_path(image_tensor) -> str:
    try:
        arr = _tensor_to_numpy(image_tensor)
        if arr is None:
            return ""

        arr = np.asarray(arr)

        if arr.ndim == 4:
            arr = arr[0]
        elif arr.ndim != 3:
            return ""

        if arr.shape[-1] != 3:
            return ""

        if arr.dtype != np.uint8:
            arr = np.clip(arr * 255.0, 0, 255).astype(np.uint8)

        out_dir = folder_paths.get_temp_directory()
        os.makedirs(out_dir, exist_ok=True)

        filename = f"media_preview_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}.png"
        out_path = os.path.join(out_dir, filename)

        Image.fromarray(arr).save(out_path)
        return _norm(out_path)

    except Exception as e:
        print(f"[MediaPreview] image temp save failed: {e}")
        return ""


def _save_mask_tensor_to_temp_path(mask_tensor) -> str:
    try:
        arr = _tensor_to_numpy(mask_tensor)
        if arr is None:
            return ""

        arr = np.asarray(arr)

        if arr.ndim == 3:
            arr = arr[0]
        elif arr.ndim != 2:
            return ""

        if arr.dtype != np.uint8:
            arr = np.clip(arr * 255.0, 0, 255).astype(np.uint8)

        rgb = np.stack([arr, arr, arr], axis=-1)

        out_dir = folder_paths.get_temp_directory()
        os.makedirs(out_dir, exist_ok=True)

        filename = f"media_preview_mask_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}.png"
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

        path = ""

        # ===== 1) media_path 最優先 =====
        mp = (media_path or "").strip()

        if mp:
            if _is_url(mp):
                if _is_media_file(mp):
                    path = mp
            else:
                path = _resolve_local_file(mp)

        # ===== 2) base_dir + media =====
        if not path:
            base = (base_dir or "").strip()
            med = (media or "").strip()
            if base and med:
                path = _resolve_local_file(os.path.join(base, med))

        # ===== 3) image fallback =====
        if not path and image is not None:
            path = _save_image_tensor_to_temp_path(image)

        # ===== 4) mask fallback =====
        if not path and mask is not None:
            path = _save_mask_tensor_to_temp_path(mask)

        # ===== 5) base_dir best =====
        if not path:
            base = (base_dir or "").strip()
            if base:
                best = _pick_best_file(_realpath(base))
                if best:
                    path = best

        print(f"[MediaPreview.run] resolved={path!r}")

        set_preview_path(unique_id, path)

        if image is not None:
            out_image = image
        elif path and _is_image_file(path) and not _is_url(path):
            out_image = _load_image_as_tensor(path)
        else:
            out_image = _make_empty_image()

        if mask is not None:
            out_mask = mask
        elif path and _is_image_file(path) and not _is_url(path):
            out_mask = _load_mask_from_image(path)
        else:
            out_mask = _make_empty_mask()

        return (path, out_image, out_mask)

try:
    register_routes()
except Exception as e:
    print("[MediaPreview] route register failed at import:", e)