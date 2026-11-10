from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
import uuid
import random

router = APIRouter(prefix="", tags=["NoteCast Studio Backend"])

class MpesaPushRequest(BaseModel):
    phone_number: str
    plan_name: str
    amount: float

class ReferralOptInRequest(BaseModel):
    mpesa_number: str
    accepted_terms: bool

# --- PAYMENTS & TRANSACTIONS ---
@router.get("/payments/my-transactions")
async def get_my_transactions(current_user: dict = Depends(lambda: {"id": "mock_user_id"})):
    # Replace with real Supabase DB fetch: supabase.table("transactions").select("*").eq("user_id", current_user["id"]).execute()
    return [
        {
            "id": "TXN_984125783",
            "plan_name": "Standard Plan (Monthly)",
            "amount": 800.0,
            "status": "COMPLETED",
            "created_at": "2026-11-01T10:30:00Z"
        }
    ]

@router.post("/payments/stk-push")
async def trigger_stk_push(payload: MpesaPushRequest, current_user: dict = Depends(lambda: {"id": "mock_user_id"})):
    # Simulate Daraja API STK Push initiation
    tx_id = f"MPESA_{uuid.uuid4().hex[:10].upper()}"
    return {
        "status": "PENDING",
        "transaction_id": tx_id,
        "message": f"STK push sent to {payload.phone_number} for KES {payload.amount}"
    }

@router.get("/payments/status/{transaction_id}")
async def check_payment_status(transaction_id: str):
    # In production, check Safaricom Daraja callback status
    return {
        "transaction_id": transaction_id,
        "status": "COMPLETED"
    }

# --- REFERRALS / AFFILIATE PROGRAM ---
@router.get("/referrals/me")
async def get_referral_profile(current_user: dict = Depends(lambda: {"id": "mock_user_id"})):
    return {
        "referral_code": "MO-STUDENT-88",
        "pending_balance": 450.00,
        "total_earned": 1250.00
    }

@router.post("/referrals/opt-in")
async def referral_opt_in(payload: ReferralOptInRequest, current_user: dict = Depends(lambda: {"id": "mock_user_id"})):
    if not payload.accepted_terms:
        raise HTTPException(status_code=400, detail="You must accept the affiliate terms.")
    return {
        "status": "SUCCESS",
        "referral_code": f"MO-{random.randint(1000, 9999)}"
    }

# --- BOOK LIBRARY CATALOG ---
@router.get("/books/")
async def list_books(course: str = None, unit: str = None, topic: str = None, sort: str = "latest"):
    # Return book records filtered by query parameters
    books = [
        {
            "id": "b1",
            "title": "Distributed Systems Architecture",
            "course": "Software_Engineering",
            "unit": "Distributed_Systems",
            "topic": "Raft & Paxos",
            "popularity": 98,
            "date": "2026-09-01",
            "price": 150.0,
            "cover": "assets/covers/distributed.png"
        },
        {
            "id": "b2",
            "title": "Modern Data Engineering & Pipelines",
            "course": "Database_Management",
            "unit": "Data_Pipelines",
            "topic": "ETL & Spark",
            "popularity": 95,
            "date": "2026-10-15",
            "price": 200.0,
            "cover": "assets/covers/data.png"
        }
    ]
    return books