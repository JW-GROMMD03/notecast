from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession
from pydantic import BaseModel
from typing import List, Optional

from .. import models, auth
from ..database import get_db
from ..services import ai_generator

router = APIRouter(prefix="/socratic", tags=["socratic"])

class SocraticEvalRequest(BaseModel):
    concept: str
    user_explanation: str
    video_id: Optional[str] = None
    context_notes: Optional[str] = ""

class SocraticEvalResponse(BaseModel):
    status: str
    score: int
    feedback: str
    detected_gaps: List[str]
    socratic_question: str

@router.post("/evaluate", response_model=SocraticEvalResponse)
def evaluate_feynman_defense(
    payload: SocraticEvalRequest,
    user: models.User = Depends(auth.get_current_user),
    db: DbSession = Depends(get_db)
):
    """Evaluates student's microphone input against session notes using Socratic questioning."""
    if not payload.user_explanation or len(payload.user_explanation.strip()) < 4:
        raise HTTPException(status_code=400, detail="Please speak a clearer explanation (at least one complete sentence).")

    context = payload.context_notes or ""
    if payload.video_id:
        video = db.query(models.Video).filter(models.Video.id == payload.video_id, models.Video.user_id == user.id).first()
        if video and getattr(video, "ai_notes", None):
            context = video.ai_notes[:3500]

    result = ai_generator.evaluate_socratic_defense(
        concept=payload.concept,
        user_explanation=payload.user_explanation,
        context_notes=context
    )

    return SocraticEvalResponse(
        status=result.get("status", "needs_work"),
        score=result.get("score", 50),
        feedback=result.get("feedback", "Explanation recorded."),
        detected_gaps=result.get("detected_gaps", []),
        socratic_question=result.get("socratic_question", "What primary variable drives this outcome?")
    )