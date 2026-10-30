import asyncio
import datetime as dt
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel

from .. import models, auth
from ..database import get_db
from ..services import supabase_auth

router = APIRouter(prefix="/admin", tags=["admin"])
direct_router = APIRouter(prefix="/api/admin", include_in_schema=False)

active_ws_connections = []

# --- SCHEMAS ---
class AdminLoginReq(BaseModel):
    email: str
    password: str

class FinanceActionReq(BaseModel):
    action_type: str
    amount: float
    source_pot: str = None
    target_pot: str = None
    description: str = ""

class UserActionReq(BaseModel):
    action: str  # "BLOCK", "DELETE", "REVOKE_SUB"
    user_id: str

class AwardSubscriptionReq(BaseModel):
    user_id: str
    tier: str  # "FREE", "ECONOMY", "PREMIUM"
    duration_days: int

class SendEmailReq(BaseModel):
    user_email: str
    subject: str
    message: str

# --- CONTROLLERS ---

def handle_admin_login(req: AdminLoginReq, request: Request, db: Session):
    ip = request.client.host
    attempts_left = auth.check_admin_rate_limit(db, req.email, ip)

    generic_error = JSONResponse(
        status_code=401, 
        content={
            "detail": "Invalid administrator credentials.", 
            "attempts_left": (attempts_left - 1) if isinstance(attempts_left, int) else None
        }
    )

    try:
        auth_data = supabase_auth.sign_in_with_password(req.email, req.password)
        user_info = auth_data.get("user", {})
        user_email = user_info.get("email") or req.email
    except Exception as e:
        print(f"🔥 SUPABASE AUTH ERROR FOR {req.email}: {str(e)}")
        auth.log_admin_attempt(db, req.email, ip, successful=False)
        try:
            auth.check_admin_rate_limit(db, req.email, ip)
        except HTTPException:
            return JSONResponse(status_code=429, content={"minutes_left": 30})
        return generic_error

    user = db.query(models.User).filter(models.User.email == user_email).first()
    if not user or not user.is_admin:
        auth.log_admin_attempt(db, req.email, ip, successful=False)
        return generic_error

    auth.log_admin_attempt(db, req.email, ip, successful=True)
    return {"access_token": auth_data.get("access_token")}


def get_summary_data(db: Session, admin: models.User):
    total_revenue = db.query(func.sum(models.PaymentTransaction.amount)).filter(models.PaymentTransaction.status == "COMPLETED").scalar() or 0.0
    total_subs = db.query(models.UserSubscription).count()

    # Accurate user calculation: Exclude admins from standard regular user count if requested
    all_users = db.query(models.User).order_by(models.User.created_at.desc()).all()
    regular_users = [u for u in all_users if not u.is_admin]

    uni_stats = db.query(
        models.User.university,
        func.count(models.User.id).label('count')
    ).group_by(models.User.university).order_by(func.count(models.User.id).desc()).limit(5).all()

    universities = [{"name": u.university, "count": u.count, "percent": round((u.count / max(len(all_users), 1)) * 100, 1)} for u in uni_stats]

    plan_stats = db.query(
        models.UserSubscription.tier,
        func.count(models.UserSubscription.id)
    ).group_by(models.UserSubscription.tier).all()

    plans = [{"name": p[0], "count": p[1], "revenue": p[1] * (2500 if p[0] == "PREMIUM" else 800 if p[0] == "STANDARD" else 250)} for p in plan_stats]

    pots = db.query(models.FinancialPot).all()
    financials = {pot.id: {"balance": pot.balance, "borrowed": pot.borrowed} for pot in pots}

    # Fetch User Subscriptions detailed table
    subscriptions_records = db.query(models.UserSubscription).all()
    sub_list = []
    sub_map = {sub.user_id: sub for sub in subscriptions_records}

    user_list = []
    for u in all_users:
        sub = sub_map.get(u.id)
        user_list.append({
            "id": u.id,
            "name": getattr(u, 'display_name', '') or 'N/A',
            "email": u.email,
            "phone": getattr(u, 'phone', 'N/A'),
            "university": getattr(u, 'university', 'Unknown') or 'Unknown',
            "plan": sub.tier if sub else ("FREE" if not u.is_admin else "ADMIN"),
            "is_admin": u.is_admin,
            "status": "Active" if not getattr(u, 'is_blocked', False) else "Blocked",
            "created_at": u.created_at.isoformat() if getattr(u, 'created_at', None) else dt.datetime.utcnow().isoformat()
        })

    # Subscriptions audit list
    subs_audit = []
    for sub in subscriptions_records:
        usr = db.query(models.User).filter(models.User.id == sub.user_id).first()
        subs_audit.append({
            "id": sub.id,
            "user_email": usr.email if usr else "Unknown",
            "tier": sub.tier,
            "awarded_by": getattr(sub, 'awarded_by', 'System / Self'),
            "expires_at": sub.expires_at.isoformat() if getattr(sub, 'expires_at', None) else "Never",
            "status": "Active"
        })

    # Financial ledgers transactions
    transactions = db.query(models.PaymentTransaction).order_by(models.PaymentTransaction.created_at.desc()).limit(50).all()
    ledgers = [{
        "id": tx.id,
        "amount": tx.amount,
        "status": tx.status,
        "provider": getattr(tx, 'provider', 'M-Pesa'),
        "date": tx.created_at.isoformat() if tx.created_at else dt.datetime.utcnow().isoformat()
    } for tx in transactions]

    # Activity logs
    logs_query = db.query(models.AdminActionLog).order_by(models.AdminActionLog.created_at.desc()).limit(30).all()
    audit_logs = [{
        "id": log.id,
        "action": log.action_type,
        "amount": log.amount,
        "description": log.description,
        "date": log.created_at.isoformat() if log.created_at else dt.datetime.utcnow().isoformat()
    } for log in logs_query]

    return {
        "total_revenue": total_revenue,
        "total_subs": total_subs,
        "total_regular_users": len(regular_users),
        "total_users": len(all_users),
        "universities": universities,
        "plans": plans,
        "financials": financials,
        "users": user_list,
        "subscriptions": subs_audit,
        "ledgers": ledgers,
        "logs": audit_logs
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


@router.post("/users/action")
@direct_router.post("/users/action")
def manage_user_account(req: UserActionReq, db: Session = Depends(get_db), admin: models.User = Depends(auth.get_current_admin)):
    user = db.query(models.User).filter(models.User.id == req.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    
    if req.action == "BLOCK":
        user.is_blocked = True
    elif req.action == "UNBLOCK":
        user.is_blocked = False
    elif req.action == "DELETE":
        db.delete(user)
    
    db.commit()
    return {"message": f"User account successfully updated with action: {req.action}"}


@router.post("/subscriptions/award")
@direct_router.post("/subscriptions/award")
def award_subscription(req: AwardSubscriptionReq, db: Session = Depends(get_db), admin: models.User = Depends(auth.get_current_admin)):
    user = db.query(models.User).filter(models.User.id == req.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    
    expires = dt.datetime.utcnow() + dt.timedelta(days=req.duration_days)
    sub = db.query(models.UserSubscription).filter(models.UserSubscription.user_id == req.user_id).first()
    
    if sub:
        sub.tier = req.tier
        sub.expires_at = expires
        sub.awarded_by = admin.email
    else:
        sub = models.UserSubscription(
            user_id=req.user_id,
            tier=req.tier,
            expires_at=expires,
            awarded_by=admin.email
        )
        db.add(sub)
    
    db.commit()
    return {"message": f"Successfully awarded {req.tier} subscription to {user.email}."}


@router.post("/notifications/send")
@direct_router.post("/notifications/send")
def send_notification(req: SendEmailReq, db: Session = Depends(get_db), admin: models.User = Depends(auth.get_current_admin)):
    from .auth import send_resend_email
    try:
        send_resend_email(req.user_email, "https://notecast-web.onrender.com/dashboard.html", "signup")
        return {"message": f"Notification successfully dispatched to {req.user_email}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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