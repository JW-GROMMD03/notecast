import asyncio
import datetime as dt
import calendar
from collections import defaultdict
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
    action: str  
    user_id: str

class AwardSubscriptionReq(BaseModel):
    user_id: str
    tier: str  
    duration_days: int

class SendEmailReq(BaseModel):
    user_email: str
    subject: str
    message: str

class ExpenseReq(BaseModel):
    name: str
    amount: float
    interval_days: int
    next_due: str

class BulkEmailReq(BaseModel):
    tier: str
    university: str
    student_status: str
    course: str
    specific_email: str = ""
    subject: str
    message: str


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


def get_summary_data(db: Session, admin: models.User, period: str = "all"):
    today = dt.datetime.utcnow()
    start_date = None
    
    if period == "today":
        start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "this_week":
        start_date = today - dt.timedelta(days=today.weekday())
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "this_month":
        start_date = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    tx_query = db.query(models.PaymentTransaction).filter(models.PaymentTransaction.status == "COMPLETED")
    users_query = db.query(models.User)
    
    if start_date:
        tx_query = tx_query.filter(models.PaymentTransaction.created_at >= start_date)
        users_query = users_query.filter(models.User.created_at >= start_date)

    transactions_completed = tx_query.all()
    total_revenue = sum([float(tx.amount) for tx in transactions_completed])
    total_subs = db.query(models.UserSubscription).count()

    all_users = users_query.order_by(models.User.created_at.desc()).all()
    regular_users = all_users

    uni_stats = db.query(
        models.User.university,
        func.count(models.User.id).label('count')
    ).group_by(models.User.university).order_by(func.count(models.User.id).desc()).limit(5).all()

    universities = [{"name": u.university or 'Unknown', "count": u.count, "percent": round((u.count / max(len(all_users), 1)) * 100, 1)} for u in uni_stats]

    subscriptions_records = db.query(models.UserSubscription).all()
    sub_map = {sub.user_id: sub for sub in subscriptions_records}
    
    tier_revenue = defaultdict(float)
    for tx in transactions_completed:
        sub = sub_map.get(getattr(tx, 'user_id', None))
        tier = sub.tier if sub else "FREE"
        tier_revenue[tier] += float(tx.amount)

    plan_stats = db.query(
        models.UserSubscription.tier,
        func.count(models.UserSubscription.id)
    ).group_by(models.UserSubscription.tier).all()

    plans = [{"name": p[0], "count": p[1], "revenue": tier_revenue.get(p[0], 0.0)} for p in plan_stats]

    pots = db.query(models.FinancialPot).all()
    financials = {pot.id: {"balance": pot.balance, "borrowed": pot.borrowed} for pot in pots}
    net_worth = sum([pot.balance for pot in pots])

    last_day = calendar.monthrange(today.year, today.month)[1]
    days_to_month_end = last_day - today.day
    eom_alert = days_to_month_end <= 5

    expenses = db.query(models.RecurringExpense).order_by(models.RecurringExpense.next_due.asc()).all()
    
    # Bulletproof next_due mapping
    due_expenses_count = 0
    expense_list = []
    for ex in expenses:
        if getattr(ex, 'next_due', None):
            days_left = (ex.next_due - today).days
            if days_left <= 5:
                due_expenses_count += 1
            due_iso = ex.next_due.isoformat()
        else:
            days_left = 0
            due_iso = today.isoformat()
            
        expense_list.append({
            "id": ex.id,
            "name": ex.name,
            "amount": ex.amount,
            "interval_days": ex.interval_days,
            "next_due": due_iso,
            "status": ex.status,
            "days_left": days_left
        })

    weekly_rev, monthly_rev, yearly_rev = defaultdict(float), defaultdict(float), defaultdict(float)
    all_completed_txs = db.query(models.PaymentTransaction).filter(models.PaymentTransaction.status == "COMPLETED").all()
    
    for tx in all_completed_txs:
        if not getattr(tx, 'created_at', None): 
            continue
        yw = tx.created_at.strftime("%Y-W%W")
        ym = tx.created_at.strftime("%Y-%m")
        y = tx.created_at.strftime("%Y")
        amt = float(tx.amount)
        weekly_rev[yw] += amt
        monthly_rev[ym] += amt
        yearly_rev[y] += amt

    weekly_trend = [{"period": k, "revenue": v} for k, v in sorted(weekly_rev.items())]
    monthly_trend = [{"period": k, "revenue": v} for k, v in sorted(monthly_rev.items())]
    yearly_trend = [{"period": k, "revenue": v} for k, v in sorted(yearly_rev.items())]

    trend_status = "Neutral"
    trend_percentage = 0.0
    if len(monthly_trend) >= 2:
        last_month = monthly_trend[-1]["revenue"]
        prev_month = monthly_trend[-2]["revenue"]
        if prev_month > 0:
            trend_percentage = ((last_month - prev_month) / prev_month) * 100
            trend_status = "Climbing 📈" if trend_percentage > 0 else "Reducing 📉"

    user_list = []
    for u in all_users:
        sub = sub_map.get(u.id)
        is_super_admin = u.email in ['destinymichael941@gmail.com'] or getattr(u, 'is_admin', False)
        display_plan = "SUPER ADMIN" if is_super_admin else (sub.tier if sub else "FREE")
        
        user_list.append({
            "id": u.id,
            "name": getattr(u, 'display_name', '') or 'N/A',
            "email": u.email,
            "phone": getattr(u, 'phone', 'N/A') or 'N/A',
            "university": getattr(u, 'university', 'Unknown') or 'Unknown',
            "course": getattr(u, 'course', 'N/A') or 'N/A',
            "plan": display_plan,
            "is_admin": is_super_admin,
            "status": "Active" if not getattr(u, 'is_blocked', False) else "Blocked",
            "created_at": u.created_at.isoformat() if getattr(u, 'created_at', None) else today.isoformat()
        })

    subs_audit = []
    for u in all_users:
        sub = sub_map.get(u.id)
        is_super_admin = u.email in ['destinymichael941@gmail.com'] or getattr(u, 'is_admin', False)
        
        if sub:
            manager_label = 'System / Admin' 
            tier_val = "SUPER ADMIN" if is_super_admin else sub.tier
            expires_val = sub.expires_at.isoformat() if getattr(sub, 'expires_at', None) else "Never"
        else:
            manager_label = 'System Enabled'
            tier_val = "SUPER ADMIN" if is_super_admin else 'FREE'
            expires_val = 'Lifetime / Free'

        subs_audit.append({
            "id": sub.id if sub else f"free-{u.id}",
            "user_email": u.email,
            "tier": tier_val,
            "awarded_by": manager_label,
            "expires_at": expires_val,
            "status": "Active"
        })

    transactions = db.query(models.PaymentTransaction).order_by(models.PaymentTransaction.created_at.desc()).all()
    if start_date:
        transactions = [t for t in transactions if getattr(t, 'created_at', None) and t.created_at >= start_date]

    ledgers = [{
        "id": tx.id,
        "amount": tx.amount,
        "status": tx.status.upper() if getattr(tx, 'status', None) else "PENDING",
        "provider": getattr(tx, 'provider', 'M-Pesa'),
        "date": tx.created_at.isoformat() if getattr(tx, 'created_at', None) else today.isoformat()
    } for tx in transactions]

    logs_query = db.query(models.AdminActionLog).order_by(models.AdminActionLog.created_at.desc()).limit(30).all()

    return {
        "total_revenue": total_revenue,
        "total_subs": total_subs,
        "total_regular_users": len(regular_users), 
        "total_users": len(all_users),
        "universities": universities,
        "plans": plans,
        "financials": financials,
        "net_worth": net_worth,
        "trend_status": trend_status,
        "trend_percentage": round(trend_percentage, 1),
        "eom_alert": eom_alert,
        "days_to_month_end": days_to_month_end,
        "due_expenses_count": due_expenses_count,
        "revenue_trends": {
            "weekly": weekly_trend[-10:],
            "monthly": monthly_trend[-12:],
            "yearly": yearly_trend
        },
        "users": user_list,
        "subscriptions": subs_audit,
        "ledgers": ledgers,
        "expenses": expense_list,
        "logs": [{"action": l.action_type, "amount": l.amount, "description": l.description, "date": l.created_at.isoformat() if getattr(l, 'created_at', None) else today.isoformat()} for l in logs_query]
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


@router.post("/auth/login")
@direct_router.post("/auth/login")
def admin_login(req: AdminLoginReq, request: Request, db: Session = Depends(get_db)):
    return handle_admin_login(req, request, db)


@router.get("/dashboard/summary")
@direct_router.get("/dashboard/summary")
def get_dashboard_summary(period: str = "all", db: Session = Depends(get_db), admin: models.User = Depends(auth.get_current_admin)):
    return get_summary_data(db, admin, period)


@router.get("/library/audit")
@direct_router.get("/library/audit")
def get_admin_library_audit(db: Session = Depends(get_db), admin: models.User = Depends(auth.get_current_admin)):
    rows = (
        db.query(models.PaymentTransaction, models.Book, models.User)
        .join(models.Book, models.Book.id == models.PaymentTransaction.book_id)
        .join(models.User, models.User.id == models.PaymentTransaction.user_id)
        .filter(
            models.PaymentTransaction.status == "COMPLETED",
            models.PaymentTransaction.purchase_type == "BOOK",
        )
        .order_by(models.PaymentTransaction.created_at.desc())
        .all()
    )
    course_map = defaultdict(lambda: {"sold": 0, "revenue": 0.0})
    book_map, txs = {}, []
    
    for tx, book, user in rows:
        course = (book.course or "General").replace("_", " ")
        amt = float(tx.amount)
        course_map[course]["sold"] += 1
        course_map[course]["revenue"] += amt
        b = book_map.setdefault(book.id, {"title": book.title, "course": course, "unit": book.unit or "General",
                                          "sold_count": 0, "total_revenue": 0.0})
        b["sold_count"] += 1
        b["total_revenue"] += amt
        txs.append({"id": tx.id, "user_email": user.email, "item_name": book.title, "amount": amt,
                    "status": tx.status, "created_at": tx.created_at.isoformat() if getattr(tx, 'created_at', None) else dt.datetime.utcnow().isoformat()})
                    
    return {
        "course_summary": [{"course": k, "total_sold": v["sold"], "total_revenue": v["revenue"]} for k, v in course_map.items()],
        "book_summary": list(book_map.values()),
        "transactions": txs,
    }


@router.get("/referrals/payouts")
@direct_router.get("/referrals/payouts")
def get_admin_affiliate_payouts(db: Session = Depends(get_db), admin: models.User = Depends(auth.get_current_admin)):
    try:
        referrals = db.query(models.ReferralAccount).filter(models.ReferralAccount.pending_balance > 0).all()
        payouts = []
        for ref in referrals:
            user = db.query(models.User).filter(models.User.id == ref.user_id).first()
            payouts.append({
                "user_id": ref.user_id,
                "name": getattr(user, 'display_name', '') or (user.email if user else "Partner"),
                "mpesa_number": ref.mpesa_number or getattr(user, 'phone', 'N/A'),
                "pending_balance": float(ref.pending_balance)
            })
        return payouts
    except Exception:
        return []


@router.post("/referrals/payouts/{referrer_id}/mark-paid")
@direct_router.post("/referrals/payouts/{referrer_id}/mark-paid")
def mark_affiliate_payout_paid(referrer_id: str, db: Session = Depends(get_db), admin: models.User = Depends(auth.get_current_admin)):
    try:
        ref = db.query(models.ReferralAccount).filter(models.ReferralAccount.user_id == referrer_id).first()
        if ref:
            ref.total_earned += ref.pending_balance
            ref.pending_balance = 0.0
            db.commit()
        return {"message": "Payout marked as paid successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    
    is_super_admin = user.email in ['destinymichael941@gmail.com'] or getattr(user, 'is_admin', False)
    if is_super_admin and req.action in ("BLOCK", "DELETE"):
         raise HTTPException(status_code=403, detail="Cannot block or delete an administrative account.")
    
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
    else:
        sub = models.UserSubscription(user_id=req.user_id, tier=req.tier, expires_at=expires)
        db.add(sub)
    
    db.commit()
    return {"message": f"Successfully awarded {req.tier} subscription to {user.email}."}


@router.post("/notifications/send")
@direct_router.post("/notifications/send")
def send_notification(req: SendEmailReq, db: Session = Depends(get_db), admin: models.User = Depends(auth.get_current_admin)):
    from .auth import send_brevo_email
    try:
        send_brevo_email(req.user_email, req.message, "custom", req.subject)
        return {"message": f"Notification successfully dispatched to {req.user_email}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/expenses")
@direct_router.post("/expenses")
def add_expense(req: ExpenseReq, db: Session = Depends(get_db), admin: models.User = Depends(auth.get_current_admin)):
    due_date = dt.datetime.fromisoformat(req.next_due.replace("Z", "+00:00"))
    expense = models.RecurringExpense(name=req.name, amount=req.amount, interval_days=req.interval_days, next_due=due_date)
    db.add(expense)
    db.commit()
    return {"message": "Recurring expense added successfully."}


@router.post("/expenses/{expense_id}/pay")
@direct_router.post("/expenses/{expense_id}/pay")
def pay_expense(expense_id: str, db: Session = Depends(get_db), admin: models.User = Depends(auth.get_current_admin)):
    expense = db.query(models.RecurringExpense).filter(models.RecurringExpense.id == expense_id).first()
    if not expense: raise HTTPException(status_code=404, detail="Expense not found")
    
    pot = db.query(models.FinancialPot).filter(models.FinancialPot.id == "maintenance").first()
    if pot:
        pot.balance = max(0.0, pot.balance - expense.amount)
    
    log = models.AdminActionLog(admin_id=admin.id, action_type="EXPENSE_PAID", amount=expense.amount, description=f"Paid recurring expense: {expense.name}")
    db.add(log)

    expense.next_due = expense.next_due + dt.timedelta(days=expense.interval_days)
    db.commit()
    return {"message": f"{expense.name} marked as paid and logged to maintenance expenses."}


@router.post("/notifications/bulk")
@direct_router.post("/notifications/bulk")
def send_bulk_notifications(req: BulkEmailReq, db: Session = Depends(get_db), admin: models.User = Depends(auth.get_current_admin)):
    from .auth import send_brevo_email
    query = db.query(models.User)
    
    if req.specific_email and req.specific_email.strip() != "":
        query = query.filter(models.User.email.ilike(f"%{req.specific_email.strip()}%"))

    if req.university and req.university != "ALL":
        query = query.filter(models.User.university == req.university)
    
    if req.student_status == "STUDENT":
        query = query.filter(models.User.university != None, models.User.university != "Unknown")

    if req.course and req.course.strip() != "":
        query = query.filter(models.User.course.ilike(f"%{req.course.strip()}%"))
    
    users = query.all()
    sent_count = 0
    sub_records = {sub.user_id: sub.tier for sub in db.query(models.UserSubscription).all()}

    for u in users:
        if req.tier and req.tier != "ALL":
            is_super = u.email in ['destinymichael941@gmail.com'] or getattr(u, 'is_admin', False)
            user_tier = "SUPER ADMIN" if is_super else sub_records.get(u.id, "FREE")
            if user_tier.upper() != req.tier.upper():
                continue
        try:
            send_brevo_email(u.email, req.message, "custom", req.subject)
            sent_count += 1
        except Exception as e:
            print(f"Failed to send to {u.email}: {str(e)}")
            pass
            
    return {"message": f"Broadcast successfully dispatched to {sent_count} matching users."}


@router.websocket("/ws/metrics")
@direct_router.websocket("/ws/metrics")
async def admin_metrics_ws(websocket: WebSocket, token: str, db: Session = Depends(get_db)):
    """Fixed: Websocket handshake MUST be accepted before it can be closed."""
    await websocket.accept() 
    
    try:
        admin = auth.get_current_user_ws(token, db)
        if not admin or not admin.is_admin:
            await websocket.close(code=1008)
            return

        active_ws_connections.append(websocket)
        while True:
            await websocket.send_json({"live_users_count": len(active_ws_connections) + 12})
            await asyncio.sleep(5)
            
    except Exception:
        pass
    finally:
        if websocket in active_ws_connections:
            active_ws_connections.remove(websocket)
        try:
            await websocket.close()
        except Exception:
            pass


@router.get("/books/list")
@direct_router.get("/books/list")
def list_all_books_admin(db: Session = Depends(get_db), admin: models.User = Depends(auth.get_current_admin)):
    """Provides the admin panel with a complete list of all uploaded books and their unique IDs."""
    books = db.query(models.Book).order_by(models.Book.created_at.desc()).all()
    return [{
        "id": b.id,
        "title": b.title,
        "course": getattr(b, "course", "N/A") or "N/A",
        "unit": getattr(b, "unit", "N/A") or "N/A",
        "price": b.price,
        "file_url": getattr(b, "file_url", getattr(b, "book_file_url", None)),
        "created_at": b.created_at.isoformat() if getattr(b, 'created_at', None) else None
    } for b in books]