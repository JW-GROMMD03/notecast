from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import uuid
from datetime import datetime
import os
import logging
from supabase import create_client, Client

logger = logging.getLogger("notecast")

def get_supabase() -> Client:
    """Dynamically resolve or initialize the Supabase client at runtime."""
    # 1. Try importing from project database module
    try:
        from ..database import supabase as db_client
        if db_client:
            return db_client
    except ImportError:
        pass

    try:
        from app.database import supabase as db_client
        if db_client:
            return db_client
    except ImportError:
        pass

    # 2. Fallback: Initialize directly from environment variables at runtime
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if url and key:
        return create_client(url, key)
        
    return None

# Safe import for current user dependency with fallback
try:
    from .auth import get_current_user
except ImportError:
    try:
        from ..auth import get_current_user
    except ImportError:
        try:
            from ..dependencies import get_current_user
        except ImportError:
            async def get_current_user(request: Request = None):
                return None

router = APIRouter(prefix="/referrals", tags=["Affiliate Program"])

class ReferralOptIn(BaseModel):
    mpesa_number: str
    accepted_terms: bool

@router.get("/me")
async def get_my_referral_data(user=Depends(get_current_user)):
    """Fetch affiliate profile for the currently logged-in user."""
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=500, detail="Database client not initialized. Check SUPABASE_URL and SUPABASE_KEY environment variables.")
    
    user_id = getattr(user, 'id', None) or str(user)
    try:
        response = supabase.table('referrals').select('*').eq('user_id', user_id).execute()
        data = response.data if hasattr(response, 'data') else response
        
        if not data or len(data) == 0:
            raise HTTPException(status_code=404, detail="User not enrolled in affiliate program")
            
        return data[0]
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error("Error fetching referral data: %s", e)
        raise HTTPException(status_code=404, detail="User not enrolled in affiliate program")

@router.post("/opt-in")
async def opt_in(data: ReferralOptIn, user=Depends(get_current_user)):
    """Opt user into the affiliate program and generate a unique partner code."""
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not data.accepted_terms:
        raise HTTPException(status_code=400, detail="You must accept the terms.")
        
    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=500, detail="Database client not initialized. Check SUPABASE_URL and SUPABASE_KEY environment variables.")

    user_id = getattr(user, 'id', None) or str(user)
    user_email = getattr(user, 'email', 'user@notecast.com')

    try:
        existing = supabase.table('referrals').select('*').eq('user_id', user_id).execute()
        if existing.data and len(existing.data) > 0:
            return {"message": "Already opted in", "referral_code": existing.data[0]['referral_code']}
    except Exception as e:
        logger.warning("Referrals table check skipped or table does not exist yet: %s", e)

    referral_code = f"NC-{str(uuid.uuid4())[:8].upper()}"
    
    try:
        insert_data = {
            "user_id": str(user_id),
            "name": getattr(user, 'display_name', None) or user_email.split('@')[0],
            "mpesa_number": data.mpesa_number,
            "referral_code": referral_code,
            "pending_balance": 0.0,
            "total_earned": 0.0,
            "created_at": datetime.utcnow().isoformat()
        }
        supabase.table('referrals').insert(insert_data).execute()
    except Exception as e:
        logger.error("Failed to insert referral record: %s", e)
        raise HTTPException(status_code=500, detail=f"Database insert failed: {str(e)}")
    
    return {"message": "Partner code activated successfully", "referral_code": referral_code}

@router.get("/admin/payouts")
async def admin_get_affiliate_payouts(admin_user=Depends(get_current_user)):
    """Fetch all affiliates with a pending payout balance for Friday distribution."""
    supabase = get_supabase()
    if not supabase:
        return []
    try:
        response = supabase.table('referrals').select('*').gt('pending_balance', 0.0).execute()
        return response.data if hasattr(response, 'data') else (response or [])
    except Exception as e:
        logger.error("Error fetching admin payouts: %s", e)
        return []

@router.post("/admin/payouts/{referrer_id}/mark-paid")
async def admin_mark_payout_paid(referrer_id: str, admin_user=Depends(get_current_user)):
    """Reset pending balance to 0 and record M-Pesa payout settlement."""
    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=500, detail="Database client not initialized")
    try:
        rec = supabase.table('referrals').select('*').eq('user_id', referrer_id).execute()
        if not rec.data:
            raise HTTPException(status_code=404, detail="Referrer not found")
        
        current_pending = rec.data[0]['pending_balance']
        current_total = rec.data[0]['total_earned']

        supabase.table('referrals').update({
            "pending_balance": 0.0,
            "total_earned": current_total + current_pending,
            "last_payout_date": datetime.utcnow().isoformat()
        }).eq('user_id', referrer_id).execute()

        return {"status": "success", "message": "Payout marked as paid and transferred to total earned."}
    except Exception as e:
        logger.error("Error marking payout paid: %s", e)
        raise HTTPException(status_code=500, detail=str(e))