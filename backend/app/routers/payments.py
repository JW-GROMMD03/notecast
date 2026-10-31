import uuid
import logging
import time
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session as DbSession
from .. import models, schemas, auth
from ..database import get_db
from ..services import mpesa_service

router = APIRouter(prefix="/payments", tags=["payments"])
logger = logging.getLogger("notecast_payments")

_last_query: dict = {}

# Comprehensive Pricing Catalog with automatic short-name to canonical mapping & pass durations
PRICING_CATALOG = {
    # Quick Pass / Quick Crash Pass
    "QUICK": {"amount": 50, "type": "PLAN_SUBSCRIPTION", "canonical": "QUICK_PASS", "duration_days": 1},
    "QUICK_PASS": {"amount": 50, "type": "PLAN_SUBSCRIPTION", "canonical": "QUICK_PASS", "duration_days": 1},
    
    # Lecture / Standard Lecture Pass
    "LECTURE": {"amount": 100, "type": "PLAN_SUBSCRIPTION", "canonical": "LECTURE_PASS", "duration_days": 7},
    "LECTURE_PASS": {"amount": 100, "type": "PLAN_SUBSCRIPTION", "canonical": "LECTURE_PASS", "duration_days": 7},
    
    # Master / Extended Master Pass
    "MASTER": {"amount": 250, "type": "PLAN_SUBSCRIPTION", "canonical": "MASTER_PASS", "duration_days": 30},
    "MASTER_PASS": {"amount": 250, "type": "PLAN_SUBSCRIPTION", "canonical": "MASTER_PASS", "duration_days": 30},
    
    # Weekly / Weekly Scholar Pass
    "WEEKLY": {"amount": 800, "type": "PLAN_SUBSCRIPTION", "canonical": "WEEKLY_SCHOLAR", "duration_days": 30},
    "WEEKLY_SCHOLAR": {"amount": 800, "type": "PLAN_SUBSCRIPTION", "canonical": "WEEKLY_SCHOLAR", "duration_days": 30},
    
    # Monthly / Monthly Pro Pass
    "MONTHLY": {"amount": 2500, "type": "PLAN_SUBSCRIPTION", "canonical": "MONTHLY_PRO", "duration_days": 30},
    "MONTHLY_PRO": {"amount": 2500, "type": "PLAN_SUBSCRIPTION", "canonical": "MONTHLY_PRO", "duration_days": 30},
    
    # Legacy compatibility aliases
    "STARTUP": {"amount": 100, "type": "PLAN_SUBSCRIPTION", "canonical": "LECTURE_PASS", "duration_days": 7},
    "BASIC": {"amount": 250, "type": "PLAN_SUBSCRIPTION", "canonical": "MASTER_PASS", "duration_days": 30},
    "STANDARD": {"amount": 800, "type": "PLAN_SUBSCRIPTION", "canonical": "WEEKLY_SCHOLAR", "duration_days": 30},
    "PREMIUM": {"amount": 2500, "type": "PLAN_SUBSCRIPTION", "canonical": "MONTHLY_PRO", "duration_days": 30},

    # One-off credits & downloads
    "ECONOMY_NOTE": {"amount": 50, "type": "ECONOMY_NOTE"},
    "SINGLE_DOWNLOAD": {"amount": 20, "type": "SINGLE_DOWNLOAD"},
    "DOWNLOAD_PASS": {"amount": 20, "type": "DOWNLOAD_PASS"},
    "SINGLE_AI_NOTE": {"amount": 80, "type": "SINGLE_AI_NOTE"}
}


def _apply_result(db: DbSession, txn: models.PaymentTransaction, result_code, desc=""):
    if txn.status != "PENDING":
        return
        
    if int(result_code) == 0:
        txn.status = "COMPLETED"
        now_utc = datetime.now(timezone.utc)
        
        if txn.purchase_type == "PLAN_SUBSCRIPTION":
            catalog_entry = PRICING_CATALOG.get(txn.target_tier, {})
            canonical_tier = catalog_entry.get("canonical", txn.target_tier)
            duration_days = catalog_entry.get("duration_days", 30)

            sub = db.query(models.UserSubscription).filter(
                models.UserSubscription.user_id == txn.user_id
            ).first()
            
            if not sub:
                sub = models.UserSubscription(
                    id=str(uuid.uuid4()), 
                    user_id=txn.user_id,
                    starts_at=now_utc
                )
                db.add(sub)
                
            sub.tier = canonical_tier
            sub.status = "active"
            sub.expires_at = now_utc + timedelta(days=duration_days)
            
            user = db.query(models.User).filter(models.User.id == txn.user_id).first()
            if user:
                user.plan = canonical_tier

        elif txn.purchase_type == "DOWNLOAD_PASS":
            user = db.query(models.User).filter(models.User.id == txn.user_id).first()
            if user:
                current_expiry = getattr(user, "unlimited_downloads_until", None)
                base_time = max(current_expiry.replace(tzinfo=timezone.utc) if current_expiry else now_utc, now_utc)
                user.unlimited_downloads_until = base_time + timedelta(days=7)
                
            credit = models.OneOffCredit(
                id=str(uuid.uuid4()),
                user_id=txn.user_id,
                credit_type=txn.purchase_type,
                is_redeemed=True
            )
            db.add(credit)

        else:
            credit = models.OneOffCredit(
                id=str(uuid.uuid4()),
                user_id=txn.user_id,
                credit_type=txn.purchase_type,
                is_redeemed=False
            )
            db.add(credit)
        
        db.commit()
    else:
        logger.warning(f"Payment failed {txn.id}: {desc}")
        txn.status = "FAILED"
        db.commit()


@router.post("/stk-push")
def initiate_payment(
    body: schemas.PaymentRequest, 
    db: DbSession = Depends(get_db), 
    user: models.User = Depends(auth.get_current_user)
):
    """Triggers M-Pesa STK Push via Daraja API and records a pending transaction."""
    plan_key = body.plan_name.strip().upper()
    if plan_key not in PRICING_CATALOG:
        raise HTTPException(status_code=400, detail="Invalid plan or token code.")
    
    catalog_item = PRICING_CATALOG[plan_key]
    amount = catalog_item["amount"]
    purchase_type = catalog_item["type"]
    canonical_tier = catalog_item.get("canonical", plan_key) if purchase_type == "PLAN_SUBSCRIPTION" else None

    try:
        res, formatted_phone = mpesa_service.initiate_stk_push(body.phone_number, amount, plan_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Daraja API Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to connect to Safaricom.")

    if res.get("ResponseCode") == "0":
        internal_tx_id = f"tx_{uuid.uuid4().hex[:12]}"
        
        new_tx = models.PaymentTransaction(
            id=internal_tx_id,
            user_id=user.id,
            merchant_request_id=res.get("MerchantRequestID"),
            checkout_request_id=res.get("CheckoutRequestID"),
            phone_number=formatted_phone,
            amount=amount,
            purchase_type=purchase_type,
            target_tier=canonical_tier if purchase_type == "PLAN_SUBSCRIPTION" else None,
            status="PENDING"
        )
        db.add(new_tx)
        db.commit()

        logger.info(f"STK Push initiated for {formatted_phone}, Amount: KES {amount}, Tier: {canonical_tier}")
        return {
            "message": "STK Push sent. Please check your phone to enter your PIN.",
            "transaction_id": internal_tx_id,
            "checkout_request_id": res.get("CheckoutRequestID")
        }

    error_msg = res.get("errorMessage", "Safaricom rejected STK Push request.")
    raise HTTPException(status_code=400, detail=error_msg)


@router.post("/qr-code")
def generate_qr(
    body: schemas.PaymentRequest, 
    user: models.User = Depends(auth.get_current_user)
):
    """Generates a Safaricom Dynamic QR Code for desktop users to scan."""
    plan_key = body.plan_name.strip().upper()
    if plan_key not in PRICING_CATALOG:
        raise HTTPException(status_code=400, detail="Invalid plan name.")
    
    amount = PRICING_CATALOG[plan_key]["amount"]
    
    try:
        qr_code_base64 = mpesa_service.generate_qr_code(amount, merchant_name="Vectis unknown")
        return {"qr_code": qr_code_base64}
    except Exception as e:
        logger.error(f"QR Code Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to connect to Safaricom QR service.")


@router.post("/callback")
async def mpesa_callback(request: Request, db: DbSession = Depends(get_db)):
    """Automatic webhook invoked by Safaricom Daraja when payment completes or fails."""
    payload = await request.json()
    logger.info(f"CALLBACK RECEIVED: {payload}")
    cb = payload.get("Body", {}).get("stkCallback", {})
    
    txn = db.query(models.PaymentTransaction).filter(
        models.PaymentTransaction.checkout_request_id == cb.get("CheckoutRequestID")
    ).first()
    
    if not txn:
        return {"ResultCode": 1, "ResultDesc": "Transaction not found"}
        
    _apply_result(db, txn, cb.get("ResultCode"), cb.get("ResultDesc", ""))
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


@router.get("/status/{transaction_id}", response_model=schemas.PaymentStatusOut)
def check_payment_status(
    transaction_id: str, 
    db: DbSession = Depends(get_db), 
    user: models.User = Depends(auth.get_current_user)
):
    """Frontend polling endpoint to verify transaction status."""
    tx = db.query(models.PaymentTransaction).filter(
        models.PaymentTransaction.id == transaction_id, 
        models.PaymentTransaction.user_id == user.id
    ).first()
    
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found.")

    # Ask Safaricom directly, throttled to 3s
    if tx.status == "PENDING" and tx.checkout_request_id and time.time() - _last_query.get(tx.id, 0) >= 3:
        _last_query[tx.id] = time.time()
        try:
            q = mpesa_service.query_stk_status(tx.checkout_request_id)
            if "ResultCode" in q:
                result_code = str(q["ResultCode"])
                
                if result_code in ["0", "1032"]:
                    _apply_result(db, tx, q["ResultCode"], q.get("ResultDesc", ""))
                    db.refresh(tx)
                else:
                    logger.info(f"Ignoring intermediate Safaricom failure {result_code} for {tx.id} to allow Fuliza processing.")
                    
        except Exception as e:
            logger.warning(f"STK query failed for {tx.id}: {e}")

    return {"status": tx.status}