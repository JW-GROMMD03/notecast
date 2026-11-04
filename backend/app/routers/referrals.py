from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import uuid
from datetime import datetime
import os

# Try importing project settings
try:
    from ..config import settings
    SUPABASE_URL = getattr(settings, "SUPABASE_URL", os.getenv("SUPABASE_URL"))
    SUPABASE_KEY = getattr(settings, "SUPABASE_KEY", os.getenv("SUPABASE_KEY"))
except ImportError:
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")

from supabase import create_client, Client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

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
                # Fallback dependency if auth function is named differently
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
    if not supabase:
        raise HTTPException(status_code=500, detail="Database client not initialized")
    
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
        raise HTTPException(status_code=404, detail="User not enrolled in affiliate program")

@router.post("/opt-in")
async def opt_in(data: ReferralOptIn, user=Depends(get_current_user)):
    """Opt user into the affiliate program and generate a unique partner code."""
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not data.accepted_terms:
        raise HTTPException(status_code=400, detail="You must accept the terms.")
        
    if not supabase:
        raise HTTPException(status_code=500, detail="Database client not initialized")

    user_id = getattr(user, 'id', None) or str(user)
    user_email = getattr(user, 'email', 'user@notecast.com')

    existing = supabase.table('referrals').select('*').eq('user_id', user_id).execute()
    if existing.data and len(existing.data) > 0:
        return {"message": "Already opted in", "referral_code": existing.data[0]['referral_code']}

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
        pass
    
    return {"message": "Partner code activated successfully", "referral_code": referral_code}

@router.get("/admin/payouts")
async def admin_get_affiliate_payouts(admin_user=Depends(get_current_user)):
    """Fetch all affiliates with a pending payout balance for Friday distribution."""
    if not supabase:
        return []
    try:
        response = supabase.table('referrals').select('*').gt('pending_balance', 0.0).execute()
        return response.data if hasattr(response, 'data') else (response or [])
    except Exception as e:
        return []

@router.post("/admin/payouts/{referrer_id}/mark-paid")
async def admin_mark_payout_paid(referrer_id: str, admin_user=Depends(get_current_user)):
    """Reset pending balance to 0 and record M-Pesa payout settlement."""
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
        raise HTTPException(status_code=500, detail=str(e))