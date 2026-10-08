import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session as DbSession
from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/payments", tags=["payments"])
logger = logging.getLogger("notecast_payments")

# PLAN DIRECTORY (Matching your index.html)
PLANS = {
    "quick": {"amount": 40, "name": "Quick Crash Pass"},
    "lecture": {"amount": 60, "name": "Standard Lecture"},
    "master": {"amount": 150, "name": "Extended Master"},
    "weekly": {"amount": 500, "name": "Weekly Scholar"},
    "monthly": {"amount": 1200, "name": "Monthly Pro"}
}

def format_phone_number(phone: str) -> str:
    """Formats phone to 254XXXXXXXXX for Daraja API"""
    phone = phone.strip()
    if phone.startswith("0"):
        return "254" + phone[1:]
    if phone.startswith("+254"):
        return phone[1:]
    if phone.startswith("254"):
        return phone
    raise ValueError("Invalid phone number format")


@router.post("/stk-push")
def initiate_payment(body: schemas.PaymentRequest, db: DbSession = Depends(get_db), user: models.User = Depends(auth.get_current_user)):
    """Triggered by the frontend to start the M-Pesa STK Push"""
    if body.plan_name not in PLANS or PLANS[body.plan_name]["amount"] != body.amount:
        raise HTTPException(status_code=400, detail="Invalid plan or amount mismatch.")

    try:
        formatted_phone = format_phone_number(body.phone_number)
    except ValueError:
        raise HTTPException(status_code=400, detail="Please enter a valid Safaricom number (e.g., 0712345678).")

    # 1. Create a pending transaction in the database
    internal_tx_id = f"tx_{uuid.uuid4().hex[:8]}"
    new_tx = models.Transaction(
        id=internal_tx_id,
        user_id=user.id,
        amount=body.amount,
        plan_name=body.plan_name,
        status="pending"
    )
    db.add(new_tx)
    db.commit()

    # 2. TRIGGER DARAJA API HERE
    # In production, you will make an httpx.post() to the Safaricom Daraja API here
    # passing the formatted_phone, amount, and your webhook URL (e.g., https://notecast-53sj.onrender.com/api/payments/callback)
    
    logger.info(f"STK Push initiated for {formatted_phone}, Amount: {body.amount}")

    return {"message": "STK Push sent. Please check your phone to enter your PIN.", "transaction_id": internal_tx_id}


@router.post("/callback")
async def mpesa_callback(request: Request, db: DbSession = Depends(get_db)):
    """Safaricom hits this endpoint automatically when the user completes the PIN prompt."""
    # Note: Safaricom webhooks do not use NoteCast session cookies, so DO NOT require auth here.
    payload = await request.json()
    
    # Extract data based on Daraja Result Format
    stk_callback = payload.get("Body", {}).get("stkCallback", {})
    result_code = stk_callback.get("ResultCode")
    merchant_req_id = stk_callback.get("MerchantRequestID") # Use this to map back to your internal_tx_id in production

    # Find the transaction in DB (Mocked mapping here)
    # tx = db.query(models.Transaction).filter(...).first()
    
    if result_code == 0:
        # Success! Update DB and upgrade user account
        logger.info("Payment successful.")
        # tx.status = "completed"
        # Grant user the specific pass limits based on tx.plan_name
    else:
        # Failed or cancelled
        logger.warning(f"Payment failed: {stk_callback.get('ResultDesc')}")
        # tx.status = "failed"
        
    # db.commit()
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


@router.get("/status/{transaction_id}", response_model=schemas.PaymentStatusOut)
def check_payment_status(transaction_id: str, db: DbSession = Depends(get_db), user: models.User = Depends(auth.get_current_user)):
    """Frontend polls this endpoint to know when to show success and redirect."""
    tx = db.query(models.Transaction).filter(models.Transaction.id == transaction_id, models.Transaction.user_id == user.id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    
    return {"status": tx.status}