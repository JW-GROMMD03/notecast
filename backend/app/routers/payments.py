import uuid
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session as DbSession
from .. import models, schemas, auth
from ..database import get_db

# Import the new flat M-Pesa service
from ..services import mpesa_service

router = APIRouter(prefix="/payments", tags=["payments"])
logger = logging.getLogger("notecast_payments")

PRICING_CATALOG = {
    "STARTUP": {"amount": 100, "type": "PLAN_SUBSCRIPTION"},
    "BASIC": {"amount": 250, "type": "PLAN_SUBSCRIPTION"},
    "STANDARD": {"amount": 800, "type": "PLAN_SUBSCRIPTION"},
    "PREMIUM": {"amount": 1199, "type": "PLAN_SUBSCRIPTION"},
    "ECONOMY_NOTE": {"amount": 50, "type": "ECONOMY_NOTE"},
    "SINGLE_DOWNLOAD": {"amount": 20, "type": "SINGLE_DOWNLOAD"},
    "SINGLE_AI_NOTE": {"amount": 80, "type": "SINGLE_AI_NOTE"}
}

@router.post("/stk-push")
def initiate_payment(body: schemas.PaymentRequest, db: DbSession = Depends(get_db), user: models.User = Depends(auth.get_current_user)):
    """Triggered by the frontend to start the M-Pesa STK Push"""
    if body.plan_name not in PRICING_CATALOG:
        raise HTTPException(status_code=400, detail="Invalid plan or token code.")
    
    catalog_item = PRICING_CATALOG[body.plan_name]
    amount = catalog_item["amount"]
    purchase_type = catalog_item["type"]

    try:
        # Delegate STK push logic to the flat M-Pesa service
        res, formatted_phone = mpesa_service.initiate_stk_push(body.phone_number, amount, body.plan_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Daraja API Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to connect to Safaricom.")

    if res.get("ResponseCode") == "0":
        internal_tx_id = f"tx_{uuid.uuid4().hex[:8]}"
        
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

        logger.info(f"STK Push initiated for {formatted_phone}, Amount: {amount}")
        return {"message": "STK Push sent. Please check your phone to enter your PIN.", "transaction_id": internal_tx_id}

    error_msg = res.get("errorMessage", "Safaricom rejected STK Push request.")
    raise HTTPException(status_code=400, detail=error_msg)


@router.post("/qr-code")
def generate_qr(body: schemas.PaymentRequest, user: models.User = Depends(auth.get_current_user)):
    """Generates a Safaricom Dynamic QR Code for desktop users to scan."""
    if body.plan_name not in PRICING_CATALOG:
        raise HTTPException(status_code=400, detail="Invalid plan.")
    
    amount = PRICING_CATALOG[body.plan_name]["amount"]
    
    try:
        qr_code_base64 = mpesa_service.generate_qr_code(amount, merchant_name="Vectis unknown")
        return {"qr_code": qr_code_base64}
    except Exception as e:
        logger.error(f"QR Code Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to connect to Safaricom QR service.")


@router.post("/callback")
async def mpesa_callback(request: Request, db: DbSession = Depends(get_db)):
    """Safaricom hits this endpoint automatically when the user completes the PIN prompt."""
    payload = await request.json()
    stk_callback = payload.get("Body", {}).get("stkCallback", {})
    result_code = stk_callback.get("ResultCode")
    checkout_id = stk_callback.get("CheckoutRequestID")

    txn = db.query(models.PaymentTransaction).filter(models.PaymentTransaction.checkout_request_id == checkout_id).first()
    if not txn:
        return {"ResultCode": 1, "ResultDesc": "Transaction not found"}

    if result_code == 0:
        logger.info("Payment successful.")
        txn.status = "COMPLETED"
        
        if txn.purchase_type == "PLAN_SUBSCRIPTION":
            sub = db.query(models.UserSubscription).filter(models.UserSubscription.user_id == txn.user_id).first()
            if not sub:
                sub = models.UserSubscription(id=str(uuid.uuid4()), user_id=txn.user_id)
                db.add(sub)
            sub.tier = txn.target_tier
            sub.expires_at = datetime.utcnow() + timedelta(days=30)
            
            # Update user model directly to reflect fast frontend queries
            user = db.query(models.User).filter(models.User.id == txn.user_id).first()
            if user:
                user.plan = txn.target_tier
        else:
            # Add one-off credit
            credit = models.OneOffCredit(
                id=str(uuid.uuid4()),
                user_id=txn.user_id,
                credit_type=txn.purchase_type,
                is_redeemed=False
            )
            db.add(credit)
        
        db.commit()
    else:
        logger.warning(f"Payment failed: {stk_callback.get('ResultDesc')}")
        txn.status = "FAILED"
        db.commit()
        
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


@router.get("/status/{transaction_id}", response_model=schemas.PaymentStatusOut)
def check_payment_status(transaction_id: str, db: DbSession = Depends(get_db), user: models.User = Depends(auth.get_current_user)):
    """Frontend polls this endpoint to know when to show success and redirect."""
    tx = db.query(models.PaymentTransaction).filter(
        models.PaymentTransaction.id == transaction_id, 
        models.PaymentTransaction.user_id == user.id
    ).first()
    
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    
    return {"status": tx.status}