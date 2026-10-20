from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session as DbSession
from typing import Optional
from .. import models, auth
from ..database import get_db
from ..services import llm # Adjust import to match your LLM service location

router = APIRouter(tags=["sessions"])

@router.post("/videos/{video_id}/sessions")
def create_video_session(
    video_id: str, 
    background_tasks: BackgroundTasks, 
    seed_transcript: Optional[str] = None,
    user: models.User = Depends(auth.get_current_user), 
    db: DbSession = Depends(get_db)
):
    video = db.query(models.Video).filter(models.Video.id == video_id, models.Video.user_id == user.id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    # 1. Create the session instantly in the database
    session = models.Session(video_id=video.id)
    db.add(session)
    db.commit()
    db.refresh(session)
    
    # 2. FIX: Offload the 3-minute gemini.chat_json call to a background task
    # This prevents the request from blocking and returning 504 Timeout
    if seed_transcript:
        background_tasks.add_task(llm.seed_session_topics, video.id, session.id, seed_transcript)
        
    return {"ok": True, "session_id": str(session.id)}