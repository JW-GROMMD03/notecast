import datetime as dt
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DbSession
from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/flashcards", tags=["flashcards"])
logger = logging.getLogger("notecast_flashcards")


@router.get("/due", response_model=List[schemas.FlashcardOut])
def get_due_flashcards(
    db: DbSession = Depends(get_db),
    user: models.User = Depends(auth.get_current_user)
):
    """Fetches all flashcards scheduled for review today or earlier."""
    now_utc = dt.datetime.utcnow()
    return db.query(models.Flashcard).filter(
        models.Flashcard.user_id == user.id,
        models.Flashcard.next_review_at <= now_utc
    ).all()


@router.post("/review/{card_id}", response_model=schemas.FlashcardOut)
def review_flashcard(
    card_id: str,
    body: schemas.FlashcardReviewIn,
    db: DbSession = Depends(get_db),
    user: models.User = Depends(auth.get_current_user)
):
    """Updates card review interval based on SM-2 algorithm:
    q (quality): 0=Blackout, 3=Pass with difficulty, 5=Perfect recall.
    """
    card = db.query(models.Flashcard).filter(
        models.Flashcard.id == card_id,
        models.Flashcard.user_id == user.id
    ).first()
    if not card:
        raise HTTPException(status_code=404, detail="Flashcard not found.")

    q = body.quality
    
    # Calculate Ease Factor (EF)
    # EF' = EF + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    new_ef = card.ease_factor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    card.ease_factor = max(1.3, new_ef) # Minimum EF threshold

    if q < 3:
        # Failed recall — reset sequence
        card.repetitions = 0
        card.interval_days = 1
    else:
        # Successful recall
        if card.repetitions == 0:
            card.interval_days = 1
        elif card.repetitions == 1:
            card.interval_days = 6
        else:
            card.interval_days = int(round(card.interval_days * card.ease_factor))
        
        card.repetitions += 1

    # Schedule next review
    card.next_review_at = dt.datetime.utcnow() + dt.timedelta(days=card.interval_days)
    
    db.commit()
    db.refresh(card)
    return card