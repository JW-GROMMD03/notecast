from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import uuid
import random
import string
from datetime import datetime
import os
import logging
from supabase import create_client, Client

from .. import schemas

logger = logging.getLogger("notecast")

# Initialize Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("✅ Supabase client successfully initialized in referrals router.")
    except Exception as e:
        logger.error("❌ Failed to initialize Supabase client: %s", e)

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
admin_fallback_router = APIRouter(prefix="/admin", tags=["Affiliate Admin Fallback"])


def generate_referral_code(name: str) -> str:
    """Generates a personalized, unique referral code (e.g., MIKE-9A2F)"""
    if not name:
        name = "USER"
    # Take first 4 chars, uppercase, strip spaces
    prefix = name[:4].upper().replace(" ", "")
    # Pad with 'X' if the name is too short
    if len(prefix) < 4:
        prefix = prefix.ljust(4, 'X')
    # Generate 4 random alphanumeric characters for the suffix
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{prefix}-{suffix}"


@router.get("/me", response_model=schemas.ReferralDashboardOut)
async def get_my_referral_data(user=Depends(get_current_user)):
    """Fetch affiliate profile for the currently logged-in user."""
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not supabase:
        raise HTTPException(status_code=500, detail="Database client not initialized.")
    
    user_id = getattr(user, 'id', None) or str(user)
    try:
        response = supabase.table('referrals').select('*').eq('user_id', user_id).execute()
        data = response.data if hasattr(response, 'data') else response
        
        if not data or len(data) == 0:
            raise HTTPException(status_code=404, detail="User not enrolled in affiliate program")
            
        profile = data[0]
        return {
            "referral_code": profile.get("referral_code", ""),
            "mpesa_number": profile.get("mpesa_number", ""),
            "pending_balance": float(profile.get("pending_balance", 0.0)),
            "total_earned": float(profile.get("total_earned", 0.0))
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error("Error fetching referral data: %s", e)
        raise HTTPException(status_code=404, detail="User not enrolled in affiliate program")


@router.post("/opt-in")
async def opt_in(data: schemas.ReferralOptIn, user=Depends(get_current_user)):
    """Opt user into the affiliate program and generate a unique partner code."""
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not data.accepted_terms:
        raise HTTPException(status_code=400, detail="You must accept the terms.")
        
    if not supabase:
        raise HTTPException(status_code=500, detail="Database client not initialized.")

    user_id = getattr(user, 'id', None) or str(user)
    
    # Extract display name safely depending on how 'user' object is structured
    display_name = getattr(user, 'display_name', None)
    if not display_name and hasattr(user, 'get'):
        display_name = user.get('display_name')
    if not display_name:
        display_name = "USER"

    try:
        existing = supabase.table('referrals').select('*').eq('user_id', user_id).execute()
        if existing.data and len(existing.data) > 0:
            return {"message": "Already opted in", "referral_code": existing.data[0]['referral_code']}
    except Exception as e:
        logger.warning("Referrals table check note: %s", e)

    # Generate a personalized referral code
    referral_code = generate_referral_code(display_name)
    
    # Ensure code is strictly unique (basic collision handling loop)
    while True:
        try:
            check = supabase.table('referrals').select('referral_code').eq('referral_code', referral_code).execute()
            if not check.data or len(check.data) == 0:
                break # Code is unique
            # If collision occurs, generate a new one and try again
            referral_code = generate_referral_code(display_name)
        except Exception as e:
            logger.error("Error checking referral code uniqueness: %s", e)
            break
    
    try:
        # Exclude 'name' to prevent PGRST204 schema cache errors if column is missing
        insert_data = {
            "user_id": str(user_id),
            "mpesa_number": data.mpesa_number,
            "referral_code": referral_code,
            "pending_balance": 0.0,
            "total_earned": 0.0,
            "created_at": datetime.utcnow().isoformat()
        }
        supabase.table('referrals').insert(insert_data).execute()
        logger.info(f"Successfully generated and inserted referral code {referral_code} for user {user_id}")
    except Exception as e:
        logger.error("Failed to insert referral record: %s", e)
        raise HTTPException(status_code=500, detail=f"Database insert failed: {str(e)}")
    
    return {"message": "Partner code activated successfully", "referral_code": referral_code}

# --- ADMIN PAYOUT ENDPOINTS (Mapped across multiple prefixes to prevent 404s) ---

@router.get("/admin/payouts")
async def admin_get_affiliate_payouts_router(admin_user=Depends(get_current_user)):
    return await _fetch_payouts_logic()

@admin_fallback_router.get("/payouts")
async def admin_get_affiliate_payouts_admin(admin_user=Depends(get_current_user)):
    return await _fetch_payouts_logic()

async def _fetch_payouts_logic():
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