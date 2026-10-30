import asyncio
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel

from .. import models, auth
from ..database import get_db
from ..services import supabase_auth

# Render rewrite strips /api, so the backend sees /admin/...
router = APIRouter(prefix="/admin", tags=["admin"])
direct_router = APIRouter(prefix="/api/admin", include_in_schema=False)

active_ws_connections = []

# --- SCHEMAS ---
class AdminLoginReq(BaseModel):
    email: str
    password: str

class FinanceActionReq(BaseModel):
    action_type: str  # "BORROW" or "REPAY" or "EXPENSE"
    amount: float
    source_pot: str = None
    target_pot: str = None
    description: str = ""

# --- SHARED CONTROLLERS ---

def handle_admin_login(req: AdminLoginReq, request: Request, db: Session):
    ip = request.client.host
    attempts_left = auth.check_admin_rate_limit(db, req.email, ip)

    # Standardized generic error for ALL failures to prevent enumeration
    generic_error = JSONResponse(
        status_code=401, 
        content={
            "detail": "Invalid administrator credentials.", 
            "attempts_left": (attempts_left - 1) if isinstance(attempts_left, int) else None
        }
    )

    # 1. Attempt Auth
    try:
        res = supabase_auth.supabase.auth.sign_in_with_password({
            "email": req.email, "password": req.password
        })
    except Exception:
        auth.log_admin_attempt(db, req.email, ip, successful=False)
        try:
            auth.check_admin_rate_limit(db, req.email, ip)
        except HTTPException:
            return JSONResponse(status_code=429, content={"minutes_left": 30})
        
        return generic_error

    # 2. Check Database for Admin Privileges
    user = db.query(models.User).filter(models.User.id == res.user.id).first()
    if not user or not user.is_admin:
        auth.log_admin_attempt(db, req.email, ip, successful=False)
        return generic_error

    auth.log_admin_attempt(db, req.email, ip, successful=True)
    return {"access_token": res.session.access_token}


def get_summary_data(db: Session, admin: models.User):
    total_revenue = db.query(func.sum(models.PaymentTransaction.amount)).filter(models.PaymentTransaction.status == "COMPLETED").scalar() or 0.0
    total_subs = db.query(models.UserSubscription).count()

    total_users = db.query(models.User).count() or 1
    uni_stats = db.query(
        models.User.university,
        func.count(models.User.id).label('count')
    ).group_by(models.User.university).order_by(func.count(models.User.id).desc()).limit(5).all()

    universities = [{"name": u.university, "count": u.count, "percent": round((u.count / total_users) * 100, 1)} for u in uni_stats]

    plan_stats = db.query(
        models.UserSubscription.tier,
        func.count(models.UserSubscription.id)
    ).group_by(models.UserSubscription.tier).all()

    plans = [{"name": p[0], "count": p[1], "revenue": p[1] * (2500 if p[0] == "PREMIUM" else 800 if p[0] == "STANDARD" else 250)} for p in plan_stats]

    pots = db.query(models.FinancialPot).all()
    financials = {pot.id: {"balance": pot.balance, "borrowed": pot.borrowed} for pot in pots}

    return {
        "total_revenue": total_revenue,
        "total_subs": total_subs,
        "universities": universities,
        "plans": plans,
        "financials": financials
    }


def process_finance_action(req: FinanceActionReq, db: Session, admin: models.User):
    if req.action_type == "BORROW":
        source = db.query(models.FinancialPot).filter(models.FinancialPot.id == req.source_pot).first()
        target = db.query(models.FinancialPot).filter(models.FinancialPot.id == req.target_pot).first()
        if not source or not target:
            raise HTTPException(status_code=404, detail="Pot not found.")
        if source.balance < req.amount:
            raise HTTPException(status_code=400, detail="Insufficient funds in source pot to borrow.")

        source.balance -= req.amount
        target.balance += req.amount
        target.borrowed += req.amount

    elif req.action_type in ("REPAY", "EXPENSE"):
        target = db.query(models.FinancialPot).filter(models.FinancialPot.id == req.target_pot).first()
        if not target:
            raise HTTPException(status_code=404, detail="Pot not found.")
        if target.balance < req.amount:
            raise HTTPException(status_code=400, detail="Insufficient funds to execute expense/repayment.")

        target.balance -= req.amount
        if req.action_type == "REPAY" and target.borrowed > 0:
            target.borrowed = max(0, target.borrowed - req.amount)
    else:
        raise HTTPException(status_code=400, detail="Invalid action_type.")

    log = models.AdminActionLog(
        admin_id=admin.id, action_type=req.action_type, amount=req.amount,
        source_pot_id=req.source_pot, target_pot_id=req.target_pot, description=req.description
    )
    db.add(log)
    db.commit()
    return {"message": "Action executed successfully."}


# --- ROUTES ---

@router.post("/auth/login")
@direct_router.post("/auth/login")
def admin_login(req: AdminLoginReq, request: Request, db: Session = Depends(get_db)):
    return handle_admin_login(req, request, db)


@router.get("/dashboard/summary")
@direct_router.get("/dashboard/summary")
def get_dashboard_summary(db: Session = Depends(get_db), admin: models.User = Depends(auth.get_current_admin)):
    return get_summary_data(db, admin)


@router.post("/finance/action")
@direct_router.post("/finance/action")
def execute_finance_action(req: FinanceActionReq, db: Session = Depends(get_db), admin: models.User = Depends(auth.get_current_admin)):
    return process_finance_action(req, db, admin)


@router.websocket("/ws/metrics")
@direct_router.websocket("/ws/metrics")
async def admin_metrics_ws(websocket: WebSocket, token: str, db: Session = Depends(get_db)):
    admin = auth.get_current_user_ws(token, db)
    if not admin or not admin.is_admin:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    active_ws_connections.append(websocket)
    try:
        while True:
            await websocket.send_json({"live_users_count": len(active_ws_connections) + 12})
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in active_ws_connections:
            active_ws_connections.remove(websocket)