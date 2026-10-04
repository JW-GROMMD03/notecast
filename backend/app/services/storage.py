"""
Object storage abstraction.

Ships with a local-disk implementation so the whole stack runs with zero
cloud accounts. To move to Cloudflare R2 / S3 later, implement the same
three methods against boto3 and swap the import in routers/services —
nothing else in the app needs to change, since callers only ever deal in
storage_key strings and signed-URL paths.
"""
import base64
import uuid
from pathlib import Path
from ..config import settings


def _full_path(key: str) -> Path:
    path = settings.storage_path / key
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def save_bytes(key: str, data: bytes) -> str:
    _full_path(key).write_bytes(data)
    return key


def save_base64_image(prefix: str, b64_data: str, ext: str = "webp") -> str:
    if "," in b64_data:  # strip data: URL header if present
        b64_data = b64_data.split(",", 1)[1]
    raw = base64.b64decode(b64_data)
    key = f"frames/{prefix}/{uuid.uuid4().hex}.{ext}"
    save_bytes(key, raw)
    return key


def read_bytes(key: str) -> bytes:
    return _full_path(key).read_bytes()


def local_url(key: str) -> str:
    """Path served by the /media static mount — stands in for a signed R2 URL."""
    return f"/media/{key}"
