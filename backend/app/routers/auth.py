"""
Auth endpoints using Supabase Admin API + Brevo API with robust error handling, flat response parsing, and OAuth.
"""
import re
import logging
import random
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.exc import IntegrityError

from .. import models, schemas, auth
from ..database import get_db
from ..config import settings
from ..services import supabase_auth, ratelimit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

class OAuthCallbackIn(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int = 3600

class VerifyOtpIn(BaseModel):
    email: str
    token: str
    new_password: str = None

# =========================================================================
# PRODUCTION THIRD-PARTY MAILER (Brevo API with OTP Support)
# =========================================================================
def send_brevo_otp_email(to_email: str, otp_code: str, email_type: str):
    """Sends a professional HTML email containing a 6-digit OTP code via Brevo's HTTP API."""
    api_key = getattr(settings, "BREVO_API_KEY", None)
    if not api_key:
        raise HTTPException(
            status_code=500, 
            detail="BREVO_API_KEY is missing in backend environment variables."
        )

    if email_type == "signup":
        subject = "NoteCast — Verify your email"
        title = "Verify your email address"
        body_text = "Welcome to NoteCast! Use the 6-digit verification code below to activate your account."
    else:
        subject = "NoteCast — Reset your password"
        title = "Reset your password"
        body_text = "We received a request to reset your password. Use the 6-digit code below to set a new password."

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>{title}</title>
    </head>
    <body style="background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 40px 0; color: #0f172a;">
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #f8fafc;">
        <tr>
          <td align="center">
            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.05); max-width: 500px; margin: 0 auto; border: 1px solid #e2e8f0;">
              <tr>
                <td align="center" style="padding: 40px 40px 20px 40px;">
                  <h1 style="font-size: 24px; font-weight: 800; color: #1e293b; margin: 0;">🔥 NoteCast</h1>
                </td>
              </tr>
              <tr>
                <td align="center" style="padding: 0 40px 30px 40px;">
                  <h2 style="font-size: 18px; font-weight: 700; color: #0f172a; margin-bottom: 12px;">{title}</h2>
                  <p style="font-size: 15px; line-height: 1.6; color: #475569; margin-bottom: 24px;">{body_text}</p>
                  <div style="background: #f1f5f9; color: #4f46e5; font-size: 32px; font-weight: 800; letter-spacing: 8px; padding: 16px 24px; border-radius: 12px; display: inline-block; margin-bottom: 24px;">
                    {otp_code}
                  </div>
                  <p style="font-size: 13px; color: #94a3b8;">This code expires in 10 minutes. If you didn't request this, you can safely ignore this email.</p>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """

    sender_email = getattr(settings, "BREVO_SENDER_EMAIL", "destinymichael941@gmail.com")
    payload = {
        "sender": {"name": "NoteCast", "email": sender_email}, 
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content
    }

    try:
        response = httpx.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "api-key": api_key, 
                "Content-Type": "application/json",
                "accept": "application/json"
            },
            json=payload,
            timeout=10.0
        )
        if response.status_code >= 400:
            logger.error(f"Brevo API Error: {response.text}")
            raise HTTPException(status_code=500, detail="Email dispatch failed due to upstream mailer error.")
    except httpx.RequestError as e:
        logger.error(f"Brevo Network Error: {e}")
        raise HTTPException(status_code=500, detail="Could not reach email delivery service.")

# =========================================================================

def _upsert_profile(db: DbSession, user_id: str, email: str, display_name: str, phone: str = None, university: str = None, course: str = None) -> models.User:
    try:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        
        if not user:
            user = db.query(models.User).filter(models.User.email == email).first()
            if user:
                db.delete(user)
                db.commit()
                user = None

        if user:
            modified = False
            if display_name and not user.display_name:
                user.display_name = display_name
                modified = True
            if phone and not user.phone:
                user.phone = phone
                modified = True
            if university and user.university in ["Unknown", None, ""]:
                user.university = university
                modified = True
            if course and getattr(user, "course", None) != course:
                user.course = course
                modified = True
                
            if modified:
                db.commit()
                db.refresh(user)
            return user
            
        user = models.User(
            id=user_id, 
            email=email, 
            display_name=display_name,
            phone=phone,
            university=university or "Unknown",
            course=course
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    except Exception as e:
        db.rollback()
        logger.error(f"Database error during user upsert: {e}")
        raise HTTPException(status_code=500, detail="Internal database error while saving user profile.")


@router.get("/google-url")
def get_google_url(redirect_to: str):
    base = settings.SUPABASE_URL.rstrip("/")
    return {"url": f"{base}/auth/v1/authorize?provider=google&redirect_to={redirect_to}"}


@router.post("/oauth-callback", response_model=schemas.SessionTokensOut)
def oauth_callback(body: OAuthCallbackIn, response: Response, db: DbSession = Depends(get_db)):
    try:
        supa_user = supabase_auth.get_user(body.access_token)
    except supabase_auth.SupabaseAuthError:
        raise HTTPException(status_code=401, detail="Invalid or expired Google provider token.")
    
    metadata = supa_user.get("user_metadata") or {}
    display_name = metadata.get("display_name") or metadata.get("name") or metadata.get("full_name") or ""
    
    user = _upsert_profile(db, supa_user.get("id"), supa_user.get("email", ""), display_name)

    auth.set_session_cookies(response, body.access_token, body.refresh_token, body.expires_in)
    return schemas.SessionTokensOut(
        access_token=body.access_token, refresh_token=body.refresh_token, expires_in=body.expires_in,
        user_id=user.id, email=user.email, display_name=user.display_name,
    )


@router.post("/signup", response_model=schemas.MessageOut)
def signup(body: schemas.SignupIn, request: Request, db: DbSession = Depends(get_db)):
    ratelimit.enforce(
        ratelimit.client_key(request, "signup", body.email.lower()),
        settings.SIGNUP_RATE_LIMIT, settings.SIGNUP_RATE_WINDOW_SEC,
    )
    try:
        display_name = body.display_name or body.email.split("@")[0]
        
        # Use existing wrapper function to register the user
        result = supabase_auth.generate_signup_link(body.email, body.password, display_name)
        
        user_id = result.get("id") or (result.get("user") or {}).get("id")
        
        if not user_id:
            error_msg = result.get("msg") or result.get("error_description") or result.get("error") or ""
            if "already registered" in error_msg.lower() or "already exists" in error_msg.lower():
                raise HTTPException(status_code=400, detail="An account with this email already exists.")
            raise HTTPException(status_code=500, detail="Failed to create account in Supabase.")
            
        _upsert_profile(db, user_id, body.email, display_name, body.phone, body.university, getattr(body, "course", None))
        
        # Generate 6-digit OTP, attach to user metadata, and email it (ignoring the magic link)
        otp_code = f"{random.randint(100000, 999999)}"
        supabase_auth.supabase.auth.admin.update_user_by_id(user_id, {"user_metadata": {"signup_otp": otp_code}})
        send_brevo_otp_email(body.email, otp_code, "signup")

    except supabase_auth.SupabaseAuthError as e:
        msg_lower = e.message.lower()
        if "already registered" in msg_lower or "already exists" in msg_lower or e.status_code == 422:
            raise HTTPException(status_code=400, detail="An account with this email already exists.")
        raise HTTPException(status_code=e.status_code if e.status_code < 500 else 400, detail=e.message)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="An account with this email already exists.")

    return schemas.MessageOut(message="Account created — check your email for the 6-digit verification code.")


@router.post("/verify-signup-otp", response_model=schemas.MessageOut)
def verify_signup_otp(body: VerifyOtpIn, db: DbSession = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == body.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    
    try:
        supa_user = supabase_auth.supabase.auth.admin.get_user_by_id(user.id)
        metadata = supa_user.user.user_metadata if supa_user and supa_user.user else {}
        stored_otp = metadata.get("signup_otp")

        if not stored_otp or stored_otp != body.token:
            raise HTTPException(status_code=400, detail="Invalid or expired verification code.")
        
        supabase_auth.supabase.auth.admin.update_user_by_id(user.id, {
            "email_confirm": True,
            "user_metadata": {**metadata, "signup_otp": None}
        })
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"OTP verification failed: {e}")
        raise HTTPException(status_code=400, detail="Verification failed.")

    return schemas.MessageOut(message="Email successfully verified! You can now sign in.")


@router.post("/login", response_model=schemas.SessionTokensOut)
def login(body: schemas.LoginIn, request: Request, response: Response, db: DbSession = Depends(get_db)):
    ratelimit.enforce(
        ratelimit.client_key(request, "login", body.email.lower()),
        settings.LOGIN_RATE_LIMIT, settings.LOGIN_RATE_WINDOW_SEC,
    )
    try:
        result = supabase_auth.sign_in_with_password(body.email, body.password)
    except supabase_auth.SupabaseAuthError:
        raise HTTPException(status_code=401, detail="Incorrect email or password, or the account isn't verified yet.")

    res_dict = result.model_dump() if hasattr(result, "model_dump") else result
    access_token = res_dict.get("access_token")
    refresh_token = res_dict.get("refresh_token")
    expires_in = res_dict.get("expires_in", 3600)
    
    supa_user = res_dict.get("user", {})
    display_name = (supa_user.get("user_metadata") or {}).get("display_name", "")

    user = _upsert_profile(db, supa_user.get("id"), supa_user.get("email", body.email), display_name)

    auth.set_session_cookies(response, access_token, refresh_token, expires_in)
    return schemas.SessionTokensOut(
        access_token=access_token, refresh_token=refresh_token, expires_in=expires_in,
        user_id=user.id, email=user.email, display_name=user.display_name,
    )


@router.post("/refresh", response_model=schemas.SessionTokensOut)
def refresh(body: schemas.RefreshIn, request: Request, response: Response, db: DbSession = Depends(get_db)):
    refresh_token = request.cookies.get(settings.REFRESH_COOKIE_NAME) or body.refresh_token
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No session to refresh")

    try:
        result = supabase_auth.refresh_session(refresh_token)
    except supabase_auth.SupabaseAuthError:
        auth.clear_session_cookies(response)
        raise HTTPException(status_code=401, detail="Session expired — please sign in again")

    res_dict = result.model_dump() if hasattr(result, "model_dump") else result
    access_token = res_dict.get("access_token")
    new_refresh_token = res_dict.get("refresh_token")
    expires_in = res_dict.get("expires_in", 3600)
    
    supa_user = res_dict.get("user", {})
    display_name = (supa_user.get("user_metadata") or {}).get("display_name", "")

    user = _upsert_profile(db, supa_user.get("id"), supa_user.get("email", ""), display_name)

    auth.set_session_cookies(response, access_token, new_refresh_token, expires_in)
    return schemas.SessionTokensOut(
        access_token=access_token, refresh_token=new_refresh_token, expires_in=expires_in,
        user_id=user.id, email=user.email, display_name=user.display_name,
    )


@router.post("/logout", response_model=schemas.MessageOut)
def logout(request: Request, response: Response):
    auth.verify_csrf(request)
    token = request.cookies.get(settings.ACCESS_COOKIE_NAME) or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if token:
        supabase_auth.sign_out(token)
    auth.clear_session_cookies(response)
    return schemas.MessageOut(message="Signed out.")


@router.post("/forgot-password", response_model=schemas.MessageOut)
def forgot_password(body: schemas.ForgotPasswordIn, request: Request):
    ratelimit.enforce(
        ratelimit.client_key(request, "forgot", body.email.lower()),
        settings.RESET_RATE_LIMIT, settings.RESET_RATE_WINDOW_SEC,
    )
    try:
        otp_code = f"{random.randint(100000, 999999)}"
        user_list = supabase_auth.supabase.auth.admin.list_users()
        target_user = next((u for u in user_list if u.email.lower() == body.email.lower()), None)
        
        if target_user:
            supabase_auth.supabase.auth.admin.update_user_by_id(target_user.id, {"user_metadata": {**target_user.user_metadata, "recovery_otp": otp_code}})
            send_brevo_otp_email(body.email, otp_code, "recovery")
    except Exception as e:
        logger.error(f"Password reset OTP generation error: {e}")
        pass
    
    return schemas.MessageOut(message="If an account exists for that email, a reset code is on its way.")


@router.post("/reset-password", response_model=schemas.MessageOut)
def reset_password(body: VerifyOtpIn, request: Request):
    ratelimit.enforce(
        ratelimit.client_key(request, "reset"),
        settings.RESET_RATE_LIMIT, settings.RESET_RATE_WINDOW_SEC,
    )
    try:
        user_list = supabase_auth.supabase.auth.admin.list_users()
        target_user = next((u for u in user_list if u.email.lower() == body.email.lower()), None)
        
        if not target_user:
            raise HTTPException(status_code=400, detail="Invalid email or reset code.")
            
        metadata = target_user.user_metadata or {}
        stored_otp = metadata.get("recovery_otp")

        if not stored_otp or stored_otp != body.token:
            raise HTTPException(status_code=400, detail="Invalid or expired reset code.")

        supabase_auth.supabase.auth.admin.update_user_by_id(target_user.id, {
            "password": body.new_password,
            "user_metadata": {**metadata, "recovery_otp": None}
        })
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Reset password error: {e}")
        raise HTTPException(status_code=400, detail="Failed to update password.")
        
    return schemas.MessageOut(message="Password updated — you can now sign in.")


@router.get("/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(auth.get_current_user)):
    return user