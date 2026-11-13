# routers/payments.py
import os
import uuid
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.exc import IntegrityError
from .. import models, schemas, auth
from ..database import get_db
from ..services import mpesa_service

router = APIRouter(prefix="/payments", tags=["payments"])
logger = logging.getLogger("notecast_payments")

_last_query: dict = {}

class STKPushRequest(BaseModel):
    phone_number: str
    plan_name: str
    amount: Optional[float] = None
    purchase_type: Optional[str] = None
    book_id: Optional[str] = None


# Comprehensive Pricing Catalog with automatic short-name to canonical mapping & pass durations
PRICING_CATALOG = {
    "QUICK": {"amount": 50, "type": "PLAN_SUBSCRIPTION", "canonical": "QUICK_PASS", "duration_days": 1},
    "QUICK_PASS": {"amount": 50, "type": "PLAN_SUBSCRIPTION", "canonical": "QUICK_PASS", "duration_days": 1},
    "LECTURE": {"amount": 100, "type": "PLAN_SUBSCRIPTION", "canonical": "LECTURE_PASS", "duration_days": 7},
    "LECTURE_PASS": {"amount": 100, "type": "PLAN_SUBSCRIPTION", "canonical": "LECTURE_PASS", "duration_days": 7},
    "MASTER": {"amount": 250, "type": "PLAN_SUBSCRIPTION", "canonical": "MASTER_PASS", "duration_days": 30},
    "MASTER_PASS": {"amount": 250, "type": "PLAN_SUBSCRIPTION", "canonical": "MASTER_PASS", "duration_days": 30},
    "WEEKLY": {"amount": 800, "type": "PLAN_SUBSCRIPTION", "canonical": "WEEKLY_SCHOLAR", "duration_days": 30},
    "WEEKLY_SCHOLAR": {"amount": 800, "type": "PLAN_SUBSCRIPTION", "canonical": "WEEKLY_SCHOLAR", "duration_days": 30},
    "MONTHLY": {"amount": 2500, "type": "PLAN_SUBSCRIPTION", "canonical": "MONTHLY_PRO", "duration_days": 30},
    "MONTHLY_PRO": {"amount": 2500, "type": "PLAN_SUBSCRIPTION", "canonical": "MONTHLY_PRO", "duration_days": 30},
    "STARTUP": {"amount": 100, "type": "PLAN_SUBSCRIPTION", "canonical": "LECTURE_PASS", "duration_days": 7},
    "BASIC": {"amount": 250, "type": "PLAN_SUBSCRIPTION", "canonical": "MASTER_PASS", "duration_days": 30},
    "STANDARD": {"amount": 800, "type": "PLAN_SUBSCRIPTION", "canonical": "WEEKLY_SCHOLAR", "duration_days": 30},
    "PREMIUM": {"amount": 2500, "type": "PLAN_SUBSCRIPTION", "canonical": "MONTHLY_PRO", "duration_days": 30},
    "ECONOMY_NOTE": {"amount": 50, "type": "ECONOMY_NOTE"},
    "SINGLE_DOWNLOAD": {"amount": 20, "type": "SINGLE_DOWNLOAD"},
    "DOWNLOAD_PASS": {"amount": 20, "type": "DOWNLOAD_PASS"},
    "SINGLE_AI_NOTE": {"amount": 80, "type": "SINGLE_AI_NOTE"}
}


def _apply_result(db: DbSession, txn: models.PaymentTransaction, result_code, desc=""):
    """
    Applies the M-Pesa callback result code to a transaction, upgrading user entitlements 
    and automatically distributing affiliate referral commissions if applicable.
    """
    if txn.status != "PENDING":
        return
        
    if result_code is None:
        return
        
    if int(result_code) == 0:
        txn.status = "COMPLETED"
        now_utc = datetime.now(timezone.utc)
        
        if txn.purchase_type == "BOOK" and txn.book_id:
            existing_purchase = db.query(models.BookPurchase).filter_by(
                user_id=txn.user_id, book_id=txn.book_id, status="COMPLETED"
            ).first()
            if not existing_purchase:
                new_purchase = models.BookPurchase(
                    id=str(uuid.uuid4()),
                    user_id=txn.user_id,
                    book_id=txn.book_id,
                    status="COMPLETED"
                )
                db.add(new_purchase)
            
        elif txn.purchase_type == "PLAN_SUBSCRIPTION":
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
            
        # --- REFERRAL EARNINGS LOGIC ---
        try:
            if txn.amount >= 100:
                logger.info(f"Evaluating referral commission for transaction {txn.id} (Amount: {txn.amount})")
                referral = db.query(models.Referral).filter(models.Referral.referred_user_id == txn.user_id).first()
                if referral:
                    # Apply 20% for Standard/Premium plans, 10% for basic transactions
                    commission_rate = 0.20 if txn.amount >= 800 else 0.10
                    commission_amount = txn.amount * commission_rate
                    
                    earning = models.ReferralEarning(
                        referrer_id=referral.referrer_id,
                        referred_user_id=txn.user_id,
                        transaction_amount=txn.amount,
                        commission_amount=commission_amount,
                        status="pending"
                    )
                    db.add(earning)
                    
                    referrer_acc = db.query(models.ReferralAccount).filter(models.ReferralAccount.user_id == referral.referrer_id).first()
                    if referrer_acc:
                        referrer_acc.pending_balance += commission_amount
                        referrer_acc.total_earned += commission_amount
                        logger.info(f"Successfully awarded {commission_amount} commission to referrer {referral.referrer_id}")
                    else:
                        logger.warning(f"Referrer {referral.referrer_id} account missing, commission logged but not balanced.")
        except Exception as ref_err:
            logger.error(f"Failed to process referral commission for txn {txn.id}: {str(ref_err)}")
        # -----------------------------------
        
        try:
            db.commit()
        except IntegrityError:       # callback and status-poll raced; the other one already granted it
            db.rollback()
    else:
        logger.warning(f"Payment failed {txn.id}: {desc}")
        txn.status = "FAILED"
        db.commit()


@router.post("/stk-push")
def initiate_payment(
    body: STKPushRequest, 
    db: DbSession = Depends(get_db), 
    user: models.User = Depends(auth.get_current_user)
):
    """Triggers M-Pesa STK Push via Daraja API and records a pending transaction."""
    book_id_override = body.book_id
    raw_plan_name = (body.plan_name or "").strip()
    
    possible_book_id = book_id_override
    if body.purchase_type == "BOOK":
        if not possible_book_id and raw_plan_name.startswith("BOOK:"):
            possible_book_id = raw_plan_name.split("BOOK:")[1]
        elif not possible_book_id:
            possible_book_id = raw_plan_name
    elif raw_plan_name.startswith("BOOK:"):
        possible_book_id = raw_plan_name.split("BOOK:")[1]
    elif not possible_book_id:
        plan_key_upper = raw_plan_name.upper()
        if plan_key_upper not in PRICING_CATALOG:
            book_check = db.query(models.Book).filter(models.Book.id == raw_plan_name).first()
            if book_check:
                possible_book_id = book_check.id

    if possible_book_id:
        book = db.query(models.Book).filter(models.Book.id == possible_book_id).first()
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
            
        owned = db.query(models.BookPurchase).filter_by(
            user_id=user.id, book_id=book.id, status="COMPLETED"
        ).first()
        if owned:
            raise HTTPException(status_code=409, detail="You already own this book")
            
        amount = float(book.price)
        purchase_type = "BOOK"
        canonical_tier = None
        plan_key = "BOOK"
        book_id_override = book.id
    else:
        plan_key = raw_plan_name.upper()
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
            target_tier=canonical_tier,
            book_id=book_id_override,
            status="PENDING"
        )
        db.add(new_tx)
        db.commit()

        logger.info(f"STK Push initiated for {formatted_phone}, Amount: KES {amount}, Tier: {canonical_tier}, Book ID: {book_id_override}")
        return {
            "message": "STK Push sent. Please check your phone to enter your PIN.",
            "transaction_id": internal_tx_id,
            "checkout_request_id": res.get("CheckoutRequestID")
        }

    error_msg = res.get("errorMessage", "Safaricom rejected STK Push request.")
    raise HTTPException(status_code=400, detail=error_msg)


@router.post("/qr-code")
def generate_qr(
    body: STKPushRequest, 
    user: models.User = Depends(auth.get_current_user)
):
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
    """Webhook from Daraja. Fail-closed: a shared secret in the URL is required."""
    expected = os.getenv("MPESA_CALLBACK_TOKEN")
    if not expected or request.query_params.get("token") != expected:
        logger.warning("Rejected callback with missing/invalid token from %s", request.client.host if request.client else "?")
        raise HTTPException(status_code=403, detail="Forbidden")

    payload = await request.json()
    cb = payload.get("Body", {}).get("stkCallback", {})
    code = cb.get("ResultCode")
    if code is None:
        return {"ResultCode": 0, "ResultDesc": "Accepted"}

    txn = db.query(models.PaymentTransaction).filter(
        models.PaymentTransaction.checkout_request_id == cb.get("CheckoutRequestID")
    ).first()
    if not txn:
        return {"ResultCode": 0, "ResultDesc": "Accepted"}

    if int(code) == 0:
        items = {i.get("Name"): i.get("Value") for i in cb.get("CallbackMetadata", {}).get("Item", [])}
        try:
            paid = float(items.get("Amount") or 0)
        except (TypeError, ValueError):
            paid = 0.0
        if paid < float(txn.amount):
            logger.error("Underpaid callback for %s: paid=%s expected=%s", txn.id, paid, txn.amount)
            txn.status = "FAILED"
            db.commit()
            return {"ResultCode": 0, "ResultDesc": "Accepted"}

    _apply_result(db, txn, code, cb.get("ResultDesc", ""))
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


@router.get("/status/{transaction_id}", response_model=schemas.PaymentStatusOut)
def check_payment_status(
    transaction_id: str, 
    db: DbSession = Depends(get_db), 
    user: models.User = Depends(auth.get_current_user)
):
    tx = db.query(models.PaymentTransaction).filter(
        models.PaymentTransaction.id == transaction_id, 
        models.PaymentTransaction.user_id == user.id
    ).first()
    
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found.")

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


@router.get("/my-transactions")
def get_user_transactions(db: DbSession = Depends(get_db), user: models.User = Depends(auth.get_current_user)):
    try:
        transactions = db.query(models.PaymentTransaction).filter(
            models.PaymentTransaction.user_id == user.id,
            models.PaymentTransaction.book_id.isnot(None)
        ).order_by(models.PaymentTransaction.created_at.desc()).all()
        
        result = []
        for tx in transactions:
            item_name = "Academic Textbook"
            if getattr(tx, "book_id", None):
                book = db.query(models.Book).filter(models.Book.id == tx.book_id).first()
                if book:
                    item_name = f"Book: {book.title}"

            result.append({
                "id": tx.id,
                "item_name": item_name,
                "amount": tx.amount,
                "status": tx.status.upper() if tx.status else "COMPLETED",
                "created_at": tx.created_at.isoformat() if tx.created_at else datetime.now(timezone.utc).isoformat()
            })
        return result
    except Exception as e:
        logger.error(f"Failed to fetch book purchase transactions for user {user.id}: {str(e)}")
        return []