from .config import MEDIA_PREVIEW_VERSION
from .node import MediaPreview

_VERSION_SUFFIX = f"v{MEDIA_PREVIEW_VERSION}"

print(f"[MediaPreview] {_VERSION_SUFFIX }")

WEB_DIRECTORY = "web"

NODE_CLASS_MAPPINGS = {
    "MediaPreview": MediaPreview,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "MediaPreview": (
        f"Media Preview({ _VERSION_SUFFIX })"
    )
}