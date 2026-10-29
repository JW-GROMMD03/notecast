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

PRICING_CATALOG = {
    "STARTUP": {"amount": 100, "type": "PLAN_SUBSCRIPTION"},
    "BASIC": {"amount": 250, "type": "PLAN_SUBSCRIPTION"},
    "STANDARD": {"amount": 800, "type": "PLAN_SUBSCRIPTION"},
    "PREMIUM": {"amount": 2500, "type": "PLAN_SUBSCRIPTION"},
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
                
            sub.tier = txn.target_tier
            sub.status = "active"
            
            if txn.target_tier == "STARTUP":
                sub.expires_at = now_utc + timedelta(days=7)
            else:
                sub.expires_at = now_utc + timedelta(days=30)
            
            user = db.query(models.User).filter(models.User.id == txn.user_id).first()
            if user:
                user.plan = txn.target_tier

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
    if body.plan_name not in PRICING_CATALOG:
        raise HTTPException(status_code=400, detail="Invalid plan or token code.")
    
    catalog_item = PRICING_CATALOG[body.plan_name]
    amount = catalog_item["amount"]
    purchase_type = catalog_item["type"]

    try:
        res, formatted_phone = mpesa_service.initiate_stk_push(body.phone_number, amount, body.plan_name)
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
            target_tier=body.plan_name if purchase_type == "PLAN_SUBSCRIPTION" else None,
            status="PENDING"
        )
        db.add(new_tx)
        db.commit()

        logger.info(f"STK Push initiated for {formatted_phone}, Amount: KES {amount}")
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
    if body.plan_name not in PRICING_CATALOG:
        raise HTTPException(status_code=400, detail="Invalid plan name.")
    
    amount = PRICING_CATALOG[body.plan_name]["amount"]
    
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
                
                # FULIZA FIX: Only apply the result immediately if it's a SUCCESS (0) or EXPLICIT CANCEL (1032)
                # If Daraja returns Insufficient Funds (1) or Timeout (1037), we ignore it and keep spinning
                # This gives the user time to navigate the Fuliza overdraft prompts on their phone!
                if result_code in ["0", "1032"]:
                    _apply_result(db, tx, q["ResultCode"], q.get("ResultDesc", ""))
                    db.refresh(tx)
                else:
                    logger.info(f"Ignoring intermediate Safaricom failure {result_code} for {tx.id} to allow Fuliza processing.")
                    
        except Exception as e:
            logger.warning(f"STK query failed for {tx.id}: {e}")

    return {"status": tx.status}