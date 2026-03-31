# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from aiohttp import web
from server import PromptServer

_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv", ".avi"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_MEDIA_EXTS = _VIDEO_EXTS | _IMAGE_EXTS

_PREVIEW_PATHS_BY_UID: dict[str, str] = {}
_PREVIEW_PATHS_BY_NODE_ID: dict[str, str] = {}

_ROUTES_REGISTERED = False

_DEFAULT_ALLOW_ROOTS = ["/workspace", "/content", "/mnt"]
_ALLOW_ROOTS = [p.strip().rstrip("/\\") for p in os.environ.get("MEDIA_PREVIEW_ALLOW_ROOTS", "").split(",") if p.strip()]
if not _ALLOW_ROOTS:
    _ALLOW_ROOTS = _DEFAULT_ALLOW_ROOTS


def _norm(p: str) -> str:
    return os.path.normpath((p or "").strip()).replace("\\", "/")


def _realpath(p: str) -> str:
    try:
        return os.path.realpath(p).replace("\\", "/")
    except Exception:
        return _norm(p)


def _is_allowed_dir(base_dir: str) -> bool:
    rp = _realpath(base_dir).rstrip("/")
    if not rp:
        return False

    for root in _ALLOW_ROOTS:
        rr = _realpath(root).rstrip("/")
        if not rr:
            continue
        if rp == rr or rp.startswith(rr + "/"):
            return True
    return False


def _is_media_file(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext in _MEDIA_EXTS


def _is_valid_filename(name: str) -> bool:
    if not name:
        return False
    if name.startswith(".") or name.startswith("._"):
        return False
    ext = os.path.splitext(name)[1].lower()
    return ext in _MEDIA_EXTS


def _list_media_flat(base_dir: str):
    base = _norm(base_dir)
    if not base:
        return []
    if not os.path.isdir(base):
        return []
    if not _is_allowed_dir(base):
        return []

    out = []
    try:
        for fn in os.listdir(base):
            p = os.path.join(base, fn)
            if not os.path.isfile(p):
                continue
            if not _is_valid_filename(fn):
                continue
            out.append(fn)
    except Exception:
        return []

    out.sort()
    return out


def _node_id_from_unique_id(unique_id: str | None) -> str:
    s = (unique_id or "").strip()
    if not s:
        return ""
    if ":" in s:
        return s.rsplit(":", 1)[-1].strip()
    return s


def set_preview_path(unique_id: str | None, path: str):
    if not unique_id:
        return

    uid = str(unique_id).strip()
    norm_path = _norm(path or "")
    node_id = _node_id_from_unique_id(uid)

    _PREVIEW_PATHS_BY_UID[uid] = norm_path

    # 後方互換用
    if node_id:
        _PREVIEW_PATHS_BY_NODE_ID[node_id] = norm_path

    print(
        f"[MediaPreview] set_preview_path "
        f"unique_id={uid!r} node_id={node_id!r} path={norm_path!r}"
    )


def _find_path_by_unique_id(unique_id: str) -> str:
    uid = (unique_id or "").strip()
    if not uid:
        return ""
    return _PREVIEW_PATHS_BY_UID.get(uid, "")


def _find_path_by_node_id(node_id: str) -> str:
    node_id = (node_id or "").strip()
    if not node_id:
        return ""

    p = _PREVIEW_PATHS_BY_NODE_ID.get(node_id, "")
    if p:
        return p

    suffix = f":{node_id}"
    for uid, path in _PREVIEW_PATHS_BY_UID.items():
        if str(uid).endswith(suffix):
            return path or ""

    return ""


def _graph_find_node(graph: dict, node_id: int):
    for n in (graph.get("nodes") or []):
        try:
            if int(n.get("id", -1)) == int(node_id):
                return n
        except Exception:
            continue
    return None


def _graph_find_link(graph: dict, target_node_id: int, target_input_slot_index: int):
    for l in (graph.get("links") or []):
        try:
            if int(l[3]) == int(target_node_id) and int(l[4]) == int(target_input_slot_index):
                return l
        except Exception:
            continue
    return None


def _extract_candidate_string_from_node(node: dict):
    wv = node.get("widgets_values")
    if not isinstance(wv, list):
        return ""

    cands = []
    for v in wv:
        if isinstance(v, str) and v.strip():
            cands.append(v.strip())

    if not cands:
        return ""

    def score(s: str):
        s2 = s.lower()
        sc = 0
        if "/" in s2 or "\\" in s2:
            sc += 3
        ext = os.path.splitext(s2)[1]
        if ext in _MEDIA_EXTS:
            sc += 5
        if s2.startswith("/workspace/"):
            sc += 2
        return sc

    cands.sort(key=score, reverse=True)
    return cands[0]


def _resolve_upstream_string(graph: dict, target_node_id: int, input_name: str, max_hops: int = 32):
    node = _graph_find_node(graph, target_node_id)
    if not node:
        return ""

    inputs = node.get("inputs") or []
    slot_index = None
    for i, inp in enumerate(inputs):
        if inp and inp.get("name") == input_name:
            slot_index = i
            break
    if slot_index is None:
        return ""

    link = _graph_find_link(graph, target_node_id, slot_index)
    if not link:
        return ""

    try:
        origin_id = int(link[1])
    except Exception:
        return ""

    cur_id = origin_id
    for _ in range(max_hops):
        n = _graph_find_node(graph, cur_id)
        if not n:
            return ""

        s = _extract_candidate_string_from_node(n)
        if s:
            return s

        ins = n.get("inputs") or []
        if not ins:
            return ""

        next_link = _graph_find_link(graph, cur_id, 0)
        if not next_link:
            return ""

        try:
            cur_id = int(next_link[1])
        except Exception:
            return ""

    return ""


def _file_stat_payload(path: str) -> dict:
    try:
        st = os.stat(path)
        return {
            "file_exists": True,
            "file_size": int(st.st_size),
            "file_mtime_ns": int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
        }
    except Exception:
        return {
            "file_exists": False,
            "file_size": 0,
            "file_mtime_ns": 0,
        }


def register_routes():
    global _ROUTES_REGISTERED
    if _ROUTES_REGISTERED:
        return

    ps = getattr(PromptServer, "instance", None)
    if ps is None or not hasattr(ps, "routes"):
        raise RuntimeError("PromptServer not ready")

    @ps.routes.get("/media_preview/ping")
    async def media_preview_ping(request):
        unique_id = (request.query.get("unique_id", "") or "").strip()
        node_id = (request.query.get("node_id", "") or "").strip()

        path = ""
        source = ""

        if unique_id:
            path = _find_path_by_unique_id(unique_id)
            if path:
                source = "unique_id"

        if not path and node_id:
            path = _find_path_by_node_id(node_id)
            if path:
                source = "node_id"

        stat_payload = _file_stat_payload(path) if path else {
            "file_exists": False,
            "file_size": 0,
            "file_mtime_ns": 0,
        }

        is_video = bool(path and os.path.splitext(path)[1].lower() in _VIDEO_EXTS)
        is_image = bool(path and os.path.splitext(path)[1].lower() in _IMAGE_EXTS)

        print(
            f"[MediaPreview] /ping "
            f"unique_id={unique_id!r} node_id={node_id!r} "
            f"path={path!r} source={source!r} exists={stat_payload['file_exists']}"
        )

        return web.json_response({
            "ok": True,
            "unique_id": unique_id,
            "node_id": node_id,
            "path": path if stat_payload["file_exists"] else "",
            "source": source,
            "is_video": is_video if stat_payload["file_exists"] else False,
            "is_image": is_image if stat_payload["file_exists"] else False,
            **stat_payload,
        })

    @ps.routes.get("/media_preview/file")
    async def media_preview_file(request):
        unique_id = (request.query.get("unique_id", "") or "").strip()
        node_id = (request.query.get("node_id", "") or "").strip()

        path = ""
        source = ""

        if unique_id:
            path = _find_path_by_unique_id(unique_id)
            if path:
                source = "unique_id"

        if not path and node_id:
            path = _find_path_by_node_id(node_id)
            if path:
                source = "node_id"

        print(
            f"[MediaPreview] /file "
            f"unique_id={unique_id!r} node_id={node_id!r} path={path!r} source={source!r}"
        )

        if not path:
            return web.Response(
                status=404,
                text=f"No preview path for unique_id={unique_id} node_id={node_id}"
            )

        path = _norm(path)

        if not _is_media_file(path):
            return web.Response(status=415, text=f"Unsupported media: {path}")

        if not os.path.isfile(path):
            return web.Response(status=404, text=f"File not found: {path}")

        return web.FileResponse(path)

    @ps.routes.get("/media_preview/list")
    async def media_preview_list(request):
        base_dir = (request.query.get("base_dir", "") or "").strip()
        items = _list_media_flat(base_dir)
        return web.json_response({"items": items})

    @ps.routes.post("/media_preview/resolve")
    async def media_preview_resolve(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"value": ""})

        graph = body.get("graph") or {}
        node_id = body.get("node_id")
        input_name = body.get("input_name") or "media_path"

        try:
            node_id = int(node_id)
        except Exception:
            return web.json_response({"value": ""})

        val = _resolve_upstream_string(graph, node_id, input_name)

        if val:
            ext = os.path.splitext(val)[1].lower()
            if ext not in _MEDIA_EXTS:
                val = ""

        print(
            f"[MediaPreview] /resolve "
            f"node_id={node_id!r} input_name={input_name!r} value={val!r}"
        )

        return web.json_response({"value": val})

    _ROUTES_REGISTERED = True
    print("[MediaPreview] routes registered")