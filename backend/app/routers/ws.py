"""
Single WebSocket per capture session carries both audio and frame
messages as JSON (base64 payloads) rather than separate binary/text
framing — simpler on the extension side, and at these payload sizes
(a few KB of opus audio, a cropped webp frame every second or two) the
base64 overhead is negligible.

Protocol (client -> server):
  {"type": "audio_chunk", "seq": int, "data_b64": str, "mime": "audio/webm"}
  {"type": "frame", "timestamp_ms": int, "data_b64": str}
  {"type": "ping"}

Protocol (server -> client):
  {"type": "transcript", "segment": {...}}
  {"type": "visual", "event": {...}}
  {"type": "note", "section": {...}}
  {"type": "error", "detail": str}
"""
import asyncio
import base64
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from ..database import SessionLocal
from .. import models, auth
from ..services import asr, vision, storage
from ..workers import pipeline

log = logging.getLogger("notecast.ws")
router = APIRouter()

AUDIO_FLUSH_MS = 5000  # buffer this much audio before calling ASR
NOTE_TRIGGER_MS = 30000  # incremental note draft cadence


class SessionBuffer:
    def __init__(self):
        self.audio_parts: list[bytes] = []
        self.audio_ms_buffered = 0
        self.last_note_ms = 0
        self.last_confirmed_ms = 0
        self.recent_transcript = ""  # rolling window used as vision context


@router.websocket("/ws/session/{session_id}")
async def session_ws(websocket: WebSocket, session_id: str, token: str = Query(...)):
    db = SessionLocal()
    user = auth.get_current_user_ws(token, db)
    if not user:
        await websocket.close(code=4401)
        db.close()
        return

    sess = db.query(models.Session).filter(models.Session.id == session_id, models.Session.user_id == user.id).first()
    if not sess:
        await websocket.close(code=4404)
        db.close()
        return

    await websocket.accept()
    buf = SessionBuffer()
    vocab_hint = ", ".join((sess.topic_model or {}).get("key_terms", []))

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            mtype = msg.get("type")

            if mtype == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue

            if mtype == "audio_chunk":
                data = base64.b64decode(msg["data_b64"])
                buf.audio_parts.append(data)
                buf.audio_ms_buffered += msg.get("duration_ms", 250)
                if buf.audio_ms_buffered >= AUDIO_FLUSH_MS:
                    await _flush_audio(websocket, db, sess, buf, vocab_hint)

            elif mtype == "frame":
                data = base64.b64decode(msg["data_b64"])
                ts_ms = msg.get("timestamp_ms", 0)
                await _handle_frame(websocket, db, sess, buf, data, ts_ms)

            else:
                await websocket.send_text(json.dumps({"type": "error", "detail": f"unknown message type {mtype}"}))

    except WebSocketDisconnect:
        log.info("session %s disconnected", session_id)
    finally:
        if buf.audio_parts:
            try:
                await _flush_audio(websocket, db, sess, buf, vocab_hint)
            except Exception:
                pass
        db.close()


async def _flush_audio(websocket: WebSocket, db, sess: models.Session, buf: SessionBuffer, vocab_hint: str):
    audio_bytes = b"".join(buf.audio_parts)
    start_ms = buf.last_confirmed_ms
    duration_ms = buf.audio_ms_buffered
    buf.audio_parts = []
    buf.audio_ms_buffered = 0
    if not audio_bytes:
        return

    try:
        result = await asyncio.to_thread(asr.transcribe_chunk, audio_bytes, "chunk.webm", vocab_hint)
    except RuntimeError as e:
        await websocket.send_text(json.dumps({"type": "error", "detail": str(e)}))
        return

    end_ms = start_ms + duration_ms
    buf.last_confirmed_ms = end_ms
    if not result["text"]:
        return

    segment = models.TranscriptSegment(
        session_id=sess.id,
        start_ms=start_ms,
        end_ms=end_ms,
        text=result["text"],
        confidence=result["confidence"],
        is_final=True,
    )
    db.add(segment)
    db.add(models.LlmJob(
        session_id=sess.id,
        provider=result.get("provider", ""),
        model=result.get("model", ""),
        purpose="asr",
        latency_ms=result["latency_ms"],
    ))
    db.commit()
    db.refresh(segment)

    buf.recent_transcript = (buf.recent_transcript + " " + result["text"])[-2000:]

    await websocket.send_text(json.dumps({
        "type": "transcript",
        "segment": {"id": segment.id, "start_ms": start_ms, "end_ms": end_ms, "text": segment.text, "confidence": segment.confidence, "is_final": True},
    }))

    if end_ms - buf.last_note_ms >= NOTE_TRIGGER_MS:
        buf.last_note_ms = end_ms
        asyncio.create_task(_run_note_draft(websocket, sess.id))


async def _run_note_draft(websocket: WebSocket, session_id: str):
    await asyncio.to_thread(pipeline.run_incremental_note, session_id)
    db = SessionLocal()
    try:
        sess = db.query(models.Session).get(session_id)
        latest = (
            db.query(models.NoteSection)
            .filter(models.NoteSection.video_id == sess.video_id)
            .order_by(models.NoteSection.order_index.desc())
            .first()
        )
        if latest:
            try:
                await websocket.send_text(json.dumps({
                    "type": "note",
                    "section": {"id": latest.id, "heading": latest.heading, "body_md": latest.body_md, "timestamp_ms": latest.timestamp_ms},
                }))
            except RuntimeError:
                pass  # socket already closed
    finally:
        db.close()


async def _handle_frame(websocket: WebSocket, db, sess: models.Session, buf: SessionBuffer, data: bytes, ts_ms: int):
    try:
        capture = await asyncio.to_thread(vision.should_capture, sess.id, data)
    except Exception as e:
        log.warning("gate error: %s", e)
        return
    if not capture:
        return

    try:
        analysis = await asyncio.to_thread(vision.analyze_frame, data, buf.recent_transcript)
    except RuntimeError as e:
        await websocket.send_text(json.dumps({"type": "error", "detail": str(e)}))
        return

    db.add(models.LlmJob(
        session_id=sess.id,
        provider=analysis.get("_provider", ""),
        model=analysis.get("_model", "vision"),
        purpose="vision",
        latency_ms=analysis.get("_latency_ms", 0),
        tokens_out=analysis.get("_tokens", 0),
    ))

    if not analysis.get("is_meaningful"):
        db.commit()
        return

    storage_key = None
    if not analysis.get("should_reconstruct"):
        storage_key = storage.save_base64_image(sess.id, base64.b64encode(data).decode())

    event = models.VisualEvent(
        session_id=sess.id,
        timestamp_ms=ts_ms,
        type=analysis.get("type", "slide"),
        storage_key=storage_key,
        ocr_text=analysis.get("extracted_text", ""),
        description=analysis.get("description", ""),
        latex=analysis.get("latex"),
        salience_score=0.8,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    await websocket.send_text(json.dumps({
        "type": "visual",
        "event": {"id": event.id, "timestamp_ms": ts_ms, "type": event.type, "description": event.description, "storage_key": storage_key},
    }))