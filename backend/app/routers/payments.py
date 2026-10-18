import uuid
import logging
import requests
import base64
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session as DbSession
from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/payments", tags=["payments"])
logger = logging.getLogger("notecast_payments")

# M-Pesa Express Configuration
MPESA_CONSUMER_KEY = "YOUR_CONSUMER_KEY"
MPESA_CONSUMER_SECRET = "YOUR_CONSUMER_SECRET"
MPESA_PASSKEY = "YOUR_PASSKEY"
MPESA_BUSINESS_SHORTCODE = "YOUR_PAYBILL_OR_TILL"
CALLBACK_URL = "https://notecast-web.onrender.com/api/payments/callback"

PRICING_CATALOG = {
    "STARTUP": {"amount": 100, "type": "PLAN_SUBSCRIPTION"},
    "BASIC": {"amount": 250, "type": "PLAN_SUBSCRIPTION"},
    "STANDARD": {"amount": 800, "type": "PLAN_SUBSCRIPTION"},
    "PREMIUM": {"amount": 1199, "type": "PLAN_SUBSCRIPTION"},
    "ECONOMY_NOTE": {"amount": 50, "type": "ECONOMY_NOTE"},
    "SINGLE_DOWNLOAD": {"amount": 20, "type": "SINGLE_DOWNLOAD"},
    "SINGLE_AI_NOTE": {"amount": 80, "type": "SINGLE_AI_NOTE"}
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

def get_mpesa_access_token():
    url = "https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    response = requests.get(url, auth=(MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET))
    return response.json().get("access_token")

@router.post("/stk-push")
def initiate_payment(body: schemas.PaymentRequest, db: DbSession = Depends(get_db), user: models.User = Depends(auth.get_current_user)):
    """Triggered by the frontend to start the M-Pesa STK Push"""
    
    if body.plan_name not in PRICING_CATALOG:
        raise HTTPException(status_code=400, detail="Invalid plan or token code.")
    
    catalog_item = PRICING_CATALOG[body.plan_name]
    
    try:
        formatted_phone = format_phone_number(body.phone_number)
    except ValueError:
        raise HTTPException(status_code=400, detail="Please enter a valid Safaricom number (e.g., 0712345678).")

    amount = catalog_item["amount"]
    purchase_type = catalog_item["type"]

    # 1. Generate M-Pesa Token and Password
    try:
        token = get_mpesa_access_token()
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        password = base64.b64encode((MPESA_BUSINESS_SHORTCODE + MPESA_PASSKEY + timestamp).encode()).decode("utf-8")
        
        headers = {"Authorization": f"Bearer {token}"}
        mpesa_body = {
            "BusinessShortCode": MPESA_BUSINESS_SHORTCODE,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": amount,
            "PartyA": formatted_phone,
            "PartyB": MPESA_BUSINESS_SHORTCODE,
            "PhoneNumber": formatted_phone,
            "CallBackURL": CALLBACK_URL,
            "AccountReference": f"NoteCast-{body.plan_name}",
            "TransactionDesc": f"Payment for {body.plan_name}"
        }

        # 2. TRIGGER DARAJA API
        res = requests.post("https://api.safaricom.co.ke/mpesa/stkpush/v1/processrequest", json=mpesa_body, headers=headers).json()
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

    raise HTTPException(status_code=500, detail="Failed to initiate M-Pesa transaction.")


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
            user.plan = txn.target_tier
            
        else:
            # Add one-off token for Economy Note, Download, or AI Note
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