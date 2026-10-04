import asyncio
import json
import base64
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session as DbSession

from ..database import SessionLocal
from .. import models, auth
from ..services import llm, providers
from ..config import settings

router = APIRouter(tags=["websockets"])
logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_connections[session_id] = websocket
        logger.info(f"WebSocket client connected successfully for session: {session_id}")

    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]
            logger.info(f"WebSocket client disconnected for session: {session_id}")

    async def send_message(self, session_id: str, message: dict):
        if session_id in self.active_connections:
            try:
                await self.active_connections[session_id].send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to {session_id}: {e}")

manager = ConnectionManager()

@router.websocket("/ws/session/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str, token: str):
    logger.info(f"WebSocket handshake initiated for session: {session_id}")
    
    try:
        user = auth.verify_token(token)
    except Exception as e:
        logger.error(f"WebSocket auth failed: {e}")
        await websocket.close(code=1008)
        return

    db = SessionLocal()
    try:
        session_record = db.query(models.Session).filter(models.Session.id == session_id).first()
        if not session_record:
            logger.error(f"WebSocket session not found in database: {session_id}")
            await websocket.close(code=1008)
            return
    except Exception as e:
        logger.error(f"WebSocket DB lookup error: {e}", exc_info=True)
        await websocket.close(code=1011)
        return
    finally:
        db.close()

    await manager.connect(websocket, session_id)
    
    buffer_start_ms = 0
    last_frame_processed_ms = 0
    FRAME_THROTTLE_MS = 60000 

    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
            except json.JSONDecodeError as json_err:
                logger.warning(f"Failed to parse incoming WebSocket JSON payload: {json_err}")
                continue

            msg_type = payload.get("type")

            if msg_type == "audio_chunk":
                chunk_b64 = payload.get("data_b64", "")
                duration_ms = payload.get("duration_ms", 2000)
                
                if not chunk_b64:
                    continue
                
                try:
                    audio_bytes = base64.b64decode(chunk_b64)
                except Exception as b64_err:
                    logger.warning(f"Failed to decode base64 audio chunk: {b64_err}")
                    continue

                asyncio.create_task(
                    process_audio_chunk(audio_bytes, buffer_start_ms, session_id)
                )
                buffer_start_ms += duration_ms

            elif msg_type == "frame":
                timestamp_ms = payload.get("timestamp_ms", 0)
                if (timestamp_ms - last_frame_processed_ms) >= FRAME_THROTTLE_MS:
                    last_frame_processed_ms = timestamp_ms
                    frame_b64 = payload.get("data_b64", "")
                    if frame_b64:
                        asyncio.create_task(
                            process_video_frame(frame_b64, timestamp_ms, session_id)
                        )

    except WebSocketDisconnect:
        manager.disconnect(session_id)
    except Exception as e:
        logger.error(f"WebSocket unexpected error in session {session_id}: {e}", exc_info=True)
        manager.disconnect(session_id)


async def process_audio_chunk(audio_bytes: bytes, start_ms: int, session_id: str):
    """Transcribes audio, streams captions instantly, and synthesizes live notes."""
    db = SessionLocal()
    try:
        transcript_text = None
        try:
            result = providers.call_with_fallback(settings.ASR_PROVIDER_ORDER, "transcribe", audio_bytes, "chunk.webm", "")
            transcript_text = result.get("text", "")
        except Exception as e:
            logger.error(f"Audio transcription failed: {e}")
            
        if transcript_text and transcript_text.strip():
            # 1. Save transcript segment
            segment = models.TranscriptSegment(
                session_id=session_id,
                start_ms=start_ms,
                text=transcript_text.strip()
            )
            db.add(segment)
            db.commit()
            db.refresh(segment)

            # 2. Broadcast transcript segment to UI
            await manager.send_message(session_id, {
                "type": "transcript_segment",
                "segment": {
                    "start_ms": start_ms,
                    "text": segment.text
                }
            })

            # 3. Check and generate live notes incrementally
            await maybe_generate_live_note(session_id, db)

    except Exception as err:
        logger.error(f"Error in process_audio_chunk task: {err}", exc_info=True)
        db.rollback()
    finally:
        db.close()


async def maybe_generate_live_note(session_id: str, db: DbSession):
    """Synthesizes a live note section when enough new transcript text accumulates."""
    try:
        session = db.query(models.Session).filter(models.Session.id == session_id).first()
        if not session:
            return

        all_segments = (
            db.query(models.TranscriptSegment)
            .filter(models.TranscriptSegment.session_id == session_id)
            .order_by(models.TranscriptSegment.start_ms)
            .all()
        )
        
        if not all_segments:
            return

        transcript_text = " ".join([s.text for s in all_segments])
        words = transcript_text.split()
        
        # Trigger new note synthesis approximately every 35+ spoken words
        existing_notes_count = db.query(models.NoteSection).filter(models.NoteSection.video_id == session.video_id).count()
        if len(words) < (existing_notes_count + 1) * 35:
            return

        recent_window = " ".join(words[-70:])
        draft = llm.draft_note_section(recent_window, visual_context="")
        
        heading = draft.get("heading")
        body_md = draft.get("body_md")

        if heading and body_md:
            note_section = models.NoteSection(
                video_id=session.video_id,
                heading=heading,
                body_md=body_md,
                order_index=existing_notes_count
            )
            db.add(note_section)
            db.commit()
            db.refresh(note_section)

            await manager.send_message(session_id, {
                "type": "note",
                "section": {
                    "id": note_section.id,
                    "heading": note_section.heading,
                    "body_md": note_section.body_md
                }
            })
    except Exception as e:
        logger.error(f"Failed to generate live note section: {e}")


async def process_video_frame(frame_b64: str, timestamp_ms: int, session_id: str):
    db = SessionLocal()
    try:
        pass
    finally:
        db.close()