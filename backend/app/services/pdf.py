import os
import tempfile
import requests
import markdown as md
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
from .. import models
from . import storage
from ..config import settings

_env = Environment(loader=FileSystemLoader(str(Path(__file__).parent.parent / "templates")))


def resolve_weasyprint_uri(storage_key: str) -> str:
    """Downloads an R2 image to a temporary file and returns a WeasyPrint-compatible file:// URI."""
    if not storage_key: return None
    s = str(storage_key).strip().replace("https://notecast-web.onrender.com/", "").replace("http://localhost:8000/", "")
    if s.startswith("api/"): s = s[4:]
    if s.startswith("/api/"): s = s[5:]

    download_url = s if s.startswith("http") else None
    if not download_url:
        try:
            url = storage.local_url(s)
            if url and url.startswith("http"): download_url = url
        except Exception: pass

    if download_url:
        try:
            resp = requests.get(download_url, timeout=5)
            if resp.status_code == 200:
                ext = os.path.splitext(s)[1] or ".webp"
                fd, temp_path = tempfile.mkstemp(suffix=ext)
                with os.fdopen(fd, 'wb') as f:
                    f.write(resp.content)
                return f"file://{os.path.abspath(temp_path)}"
        except Exception: pass

    for path in [s, f"/data/{s}", os.path.join(os.getcwd(), s), os.path.join(os.getcwd(), "static", s)]:
        if os.path.exists(path): return f"file://{os.path.abspath(path)}"
    return None


def _ts(ms: int) -> str:
    s = ms // 1000
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def render_pdf(video: models.Video, sections: list[models.NoteSection], glossary: list[dict], review_questions: list[dict]) -> bytes:
    top_level = [s for s in sections if not s.parent_id]
    top_level.sort(key=lambda s: s.order_index)
    by_parent: dict[str, list[models.NoteSection]] = {}
    for s in sections:
        if s.parent_id:
            by_parent.setdefault(s.parent_id, []).append(s)

    def build(section: models.NoteSection) -> dict:
        assets = []
        for a in section.assets:
            url = resolve_weasyprint_uri(a.storage_key)
            assets.append({"asset_type": a.asset_type, "storage_key": a.storage_key, "content": a.content, "url": url})
        
        children = sorted(by_parent.get(section.id, []), key=lambda s: s.order_index)
        return {
            "heading": section.heading,
            "body_html": md.markdown(section.body_md or ""),
            "timestamp_ms": section.timestamp_ms,
            "ts_str": _ts(section.timestamp_ms or 0),
            "verification_status": section.verification_status,
            "assets": assets,
            "children": [build(c) for c in children],
        }

    ctx = {
        "video": video,
        "duration_str": _ts((video.duration_sec or 0) * 1000),
        "sections": [build(s) for s in top_level],
        "glossary": glossary,
        "review_questions": review_questions,
    }
    
    html_str = _env.get_template("notes.html").render(**ctx)
    return HTML(string=html_str, base_url=str(settings.storage_path)).write_pdf()


def save_export(video: models.Video, pdf_bytes: bytes) -> str:
    key = f"exports/{video.user_id}/{video.id}.pdf"
    storage.save_bytes(key, pdf_bytes)
    return key