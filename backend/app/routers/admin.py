import time
import asyncio 
from typing import List, Dict
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel

from .. import models, auth
from ..database import get_db
from ..services import supabase_auth

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Track live users via simple connection counting
active_ws_connections = []

# --- SCHEMAS ---
class AdminLoginReq(BaseModel):
    email: str
    password: str

class FinanceActionReq(BaseModel):
    action_type: str # "BORROW" or "REPAY" or "EXPENSE"
    amount: float
    source_pot: str = None
    target_pot: str = None
    description: str = ""

# --- ROUTES ---

@router.post("/auth/login")
def admin_login(req: AdminLoginReq, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host
    
    # 1. Enforce Rate Limit (Throws 429 if 3 failures in 30 mins)
    attempts_left = auth.check_admin_rate_limit(db, req.email, ip)
    
    try:
        # 2. Attempt Supabase Auth
        res = supabase_auth.supabase.auth.sign_in_with_password({
            "email": req.email, "password": req.password
        })
        
        # 3. Verify Admin Status in DB
        user = db.query(models.User).filter(models.User.id == res.user.id).first()
        if not user or not user.is_admin:
            auth.log_admin_attempt(db, req.email, ip, successful=False)
            raise HTTPException(status_code=403, detail="Account does not have administrator privileges.")
            
        auth.log_admin_attempt(db, req.email, ip, successful=True)
        return {"access_token": res.session.access_token}
        
    except Exception as e:
        auth.log_admin_attempt(db, req.email, ip, successful=False)
        # Check rate limit again to return the 'minutes_left' payload if they just hit the limit
        try:
            auth.check_admin_rate_limit(db, req.email, ip)
        except HTTPException as he:
            return JSONResponse(status_code=429, content={"minutes_left": 30})
            
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=401, content={"detail": "Invalid credentials", "attempts_left": attempts_left - 1})


@router.get("/dashboard/summary")
def get_dashboard_summary(db: Session = Depends(get_db), admin: models.User = Depends(auth.get_current_admin)):
    """Fetches full Saaslu UI Payload: Revenue, Subscriptions, Universities, and Financial Pots."""
    
    # KPIs
    total_revenue = db.query(func.sum(models.PaymentTransaction.amount)).filter(models.PaymentTransaction.status == "COMPLETED").scalar() or 0.0
    total_subs = db.query(models.UserSubscription).count()
    
    # Universities Breakdown
    total_users = db.query(models.User).count() or 1
    uni_stats = db.query(
        models.User.university, 
        func.count(models.User.id).label('count')
    ).group_by(models.User.university).order_by(func.count(models.User.id).desc()).limit(5).all()
    
    universities = [{"name": u.university, "count": u.count, "percent": round((u.count / total_users) * 100, 1)} for u in uni_stats]

    # Plan Distributions
    plan_stats = db.query(
        models.UserSubscription.tier, 
        func.count(models.UserSubscription.id)
    ).group_by(models.UserSubscription.tier).all()
    
    plans = [{"name": p[0], "count": p[1], "revenue": p[1] * (2500 if p[0] == "PREMIUM" else 800 if p[0] == "STANDARD" else 250)} for p in plan_stats]

    # Financial Pots
    pots = db.query(models.FinancialPot).all()
    financials = {pot.id: {"balance": pot.balance, "borrowed": pot.borrowed} for pot in pots}

    return {
        "total_revenue": total_revenue,
        "total_subs": total_subs,
        "universities": universities,
        "plans": plans,
        "financials": financials
    }


@router.post("/finance/action")
def execute_finance_action(req: FinanceActionReq, db: Session = Depends(get_db), admin: models.User = Depends(auth.get_current_admin)):
    """Handles expenses, borrowing across pots, and repayments."""
    if req.action_type == "BORROW":
        source = db.query(models.FinancialPot).filter(models.FinancialPot.id == req.source_pot).first()
        target = db.query(models.FinancialPot).filter(models.FinancialPot.id == req.target_pot).first()
        
        if source.balance < req.amount:
            raise HTTPException(status_code=400, detail="Insufficient funds in source pot to borrow.")
            
        source.balance -= req.amount
        target.balance += req.amount
        target.borrowed += req.amount # Record the deficit
        
    elif req.action_type == "REPAY" or req.action_type == "EXPENSE":
        target = db.query(models.FinancialPot).filter(models.FinancialPot.id == req.target_pot).first()
        if target.balance < req.amount:
            raise HTTPException(status_code=400, detail="Insufficient funds to execute expense/repayment.")
            
        target.balance -= req.amount
        if req.action_type == "REPAY" and target.borrowed > 0:
            target.borrowed = max(0, target.borrowed - req.amount)
            
    # Log the action
    log = models.AdminActionLog(
        admin_id=admin.id, action_type=req.action_type, amount=req.amount,
        source_pot_id=req.source_pot, target_pot_id=req.target_pot, description=req.description
    )
    db.add(log)
    db.commit()
    return {"message": "Action executed successfully."}


@router.websocket("/ws/metrics")
async def admin_metrics_ws(websocket: WebSocket, token: str, db: Session = Depends(get_db)):
    """Streams live user counts and activity to the dashboard."""
    admin = auth.get_current_user_ws(token, db)
    if not admin or not admin.is_admin:
        await websocket.close(code=1008)
        return
        
    await websocket.accept()
    active_ws_connections.append(websocket)
    
    try:
        while True:
            await websocket.send_json({"live_users_count": len(active_ws_connections) + 12}) # Base count offset for UX
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        active_ws_connections.remove(websocket)