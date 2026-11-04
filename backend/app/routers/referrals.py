import uuid
import random
import string
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession
from typing import List

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/referrals", tags=["referrals"])

def generate_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

@router.post("/opt-in", response_model=schemas.ReferralDashboardOut)
def opt_in_referral(
    body: schemas.ReferralOptIn, 
    db: DbSession = Depends(get_db),
    user: models.User = Depends(auth.get_current_user)
):
    if not body.accepted_terms:
        raise HTTPException(status_code=400, detail="You must accept the terms to join.")
        
    existing = db.query(models.ReferralAccount).filter(models.ReferralAccount.user_id == user.id).first()
    if existing:
        return schemas.ReferralDashboardOut(
            referral_code=existing.referral_code,
            mpesa_number=existing.mpesa_number,
            pending_balance=existing.pending_balance,
            total_earned=existing.total_earned
        )
        
    new_account = models.ReferralAccount(
        user_id=user.id,
        referral_code=generate_code(),
        mpesa_number=body.mpesa_number,
        accepted_terms=True
    )
    db.add(new_account)
    db.commit()
    db.refresh(new_account)
    
    return schemas.ReferralDashboardOut(
        referral_code=new_account.referral_code,
        mpesa_number=new_account.mpesa_number,
        pending_balance=new_account.pending_balance,
        total_earned=new_account.total_earned
    )

@router.get("/me", response_model=schemas.ReferralDashboardOut)
def get_referral_dashboard(
    db: DbSession = Depends(get_db),
    user: models.User = Depends(auth.get_current_user)
):
    account = db.query(models.ReferralAccount).filter(models.ReferralAccount.user_id == user.id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Referral account not set up.")
        
    return schemas.ReferralDashboardOut(
        referral_code=account.referral_code,
        mpesa_number=account.mpesa_number,
        pending_balance=account.pending_balance,
        total_earned=account.total_earned
    )

@router.get("/admin/payouts", response_model=List[schemas.AdminPayoutOut])
def get_pending_payouts(
    db: DbSession = Depends(get_db),
    admin: models.User = Depends(auth.get_current_user)
):
    if not admin.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")
        
    accounts = db.query(models.ReferralAccount).filter(models.ReferralAccount.pending_balance > 0).all()
    results = []
    for acc in accounts:
        user = db.query(models.User).filter(models.User.id == acc.user_id).first()
        results.append(schemas.AdminPayoutOut(
            referrer_id=acc.user_id,
            name=user.display_name if user else "Unknown",
            mpesa_number=acc.mpesa_number,
            pending_balance=acc.pending_balance
        ))
    return results

@router.post("/admin/payouts/{referrer_id}/mark-paid")
def mark_payout_paid(
    referrer_id: str,
    db: DbSession = Depends(get_db),
    admin: models.User = Depends(auth.get_current_user)
):
    if not admin.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")
        
    account = db.query(models.ReferralAccount).filter(models.ReferralAccount.user_id == referrer_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")
        
    db.query(models.ReferralEarning).filter(
        models.ReferralEarning.referrer_id == referrer_id,
        models.ReferralEarning.status == "pending"
    ).update({"status": "paid"})
    
    account.pending_balance = 0.00
    db.commit()
    return {"message": "Payout marked as paid."}