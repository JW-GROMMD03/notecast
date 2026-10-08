"""
Auth endpoints using Supabase Admin API + Resend API with robust error handling, flat response parsing, and OAuth.
"""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.exc import IntegrityError

from .. import models, schemas, auth
from ..database import get_db
from ..config import settings
from ..services import supabase_auth, ratelimit

router = APIRouter(prefix="/auth", tags=["auth"])

class OAuthCallbackIn(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int = 3600

# =========================================================================
# PRODUCTION THIRD-PARTY MAILER (Resend API)
# =========================================================================
def send_resend_email(to_email: str, link: str, email_type: str):
    """Sends a professional HTML email via Resend's HTTP API, dynamically routing to Render static site."""
    api_key = getattr(settings, "RESEND_API_KEY", None)
    if not api_key:
        raise HTTPException(
            status_code=500, 
            detail="RESEND_API_KEY is missing in backend .env file."
        )

    # Automatically swap Supabase's default localhost/hash redirect for your Render production frontend
    if "localhost" in link or "127.0.0.1" in link:
        if email_type == "signup":
            link = link.replace("http://localhost:5500", "https://notecast-web.onrender.com")
            link = link.replace("http://127.0.0.1:5500", "https://notecast-web.onrender.com")
        elif email_type == "recovery":
            # Convert hash token format to route cleanly to your reset-password page on Render
            if "#access_token=" in link:
                token_part = link.split("#access_token=")[1]
                link = f"https://notecast-web.onrender.com/reset-password.html#type=recovery&access_token={token_part}"

    if email_type == "signup":
        subject = "Welcome to NoteCast — Verify your email"
        title = "Verify your email address"
        body_text = "Welcome to NoteCast! Please click the button below to verify your account and get started."
        btn_text = "Verify Account"
    else:
        subject = "NoteCast — Reset your password"
        title = "Reset your password"
        body_text = "We received a request to reset your password. Click the button below to set a new one. If you didn't request this, ignore this email."
        btn_text = "Reset Password"

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
              
              <!-- Header -->
              <tr>
                <td align="center" style="padding: 40px 40px 20px 40px;">
                  <h1 style="font-size: 24px; font-weight: 800; color: #1e293b; margin: 0;">🔥 NoteCast</h1>
                </td>
              </tr>
              
              <!-- Content -->
              <tr>
                <td align="center" style="padding: 0 40px 30px 40px;">
                  <h2 style="font-size: 20px; font-weight: 700; color: #0f172a; margin-bottom: 12px;">{title}</h2>
                  <p style="font-size: 16px; line-height: 1.6; color: #475569; margin-bottom: 32px;">
                    {body_text}
                  </p>
                  <a href="{link}" style="display: inline-block; background-color: #6366f1; color: #ffffff; font-size: 16px; font-weight: 600; text-decoration: none; padding: 14px 36px; border-radius: 8px;">{btn_text}</a>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """

    payload = {
        "from": "NoteCast <onboarding@resend.dev>",
        "to": [to_email],
        "subject": subject,
        "html": html_content
    }

    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=10.0
        )
        if response.status_code >= 400:
            print(f"❌ Resend API Error: {response.text}")
            raise HTTPException(status_code=500, detail=f"Email dispatch failed: {response.text}")
    except httpx.RequestError as e:
        print(f"❌ Resend Network Error: {e}")
        raise HTTPException(status_code=500, detail="Could not reach email delivery service.")

# =========================================================================

def _upsert_profile(db: DbSession, user_id: str, email: str, display_name: str) -> models.User:
    user = db.query(models.User).filter(
        (models.User.id == user_id) | (models.User.email == email)
    ).first()
    
    if user:
        if user.id != user_id:
            user.id = user_id
        if display_name and not user.display_name:
            user.display_name = display_name
        db.commit()
        db.refresh(user)
        return user
        
    user = models.User(id=user_id, email=email, display_name=display_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/google-url")
def get_google_url(redirect_to: str):
    """Returns the correct Supabase authorization URL to begin the Google OAuth flow."""
    base = settings.SUPABASE_URL.rstrip("/")
    return {"url": f"{base}/auth/v1/authorize?provider=google&redirect_to={redirect_to}"}


@router.post("/oauth-callback", response_model=schemas.SessionTokensOut)
def oauth_callback(body: OAuthCallbackIn, response: Response, db: DbSession = Depends(get_db)):
    """Receives the access token from the frontend, verifies it with Supabase, and logs the user in locally."""
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
        result = supabase_auth.generate_signup_link(body.email, body.password, display_name)
        
        user_id = result.get("id") or (result.get("user") or {}).get("id")
        action_link = (result.get("action_link") or (result.get("properties") or {}).get("action_link"))
        
        if not user_id or not action_link:
            error_msg = result.get("msg") or result.get("error_description") or result.get("error") or ""
            if "already registered" in error_msg.lower() or "already exists" in error_msg.lower():
                raise HTTPException(status_code=400, detail="An account with this email already exists.")
            raise HTTPException(status_code=500, detail="Failed to generate verification link.")
            
        _upsert_profile(db, user_id, body.email, display_name)
        send_resend_email(body.email, action_link, "signup")

    except supabase_auth.SupabaseAuthError as e:
        msg_lower = e.message.lower()
        if "already registered" in msg_lower or "already exists" in msg_lower or e.status_code == 422:
            raise HTTPException(status_code=400, detail="An account with this email already exists.")
        raise HTTPException(status_code=e.status_code if e.status_code < 500 else 400, detail=e.message)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="An account with this email already exists.")

    return schemas.MessageOut(message="Account created — check your email to verify it before signing in.")


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
    recovery_link = supabase_auth.generate_recovery_link(body.email)
    if recovery_link:
        send_resend_email(body.email, recovery_link, "recovery")
    else:
        raise HTTPException(status_code=500, detail="Failed to generate password reset link.")
    
    return schemas.MessageOut(message="If an account exists for that email, a reset link is on its way.")


@router.post("/reset-password", response_model=schemas.MessageOut)
def reset_password(body: schemas.ResetPasswordIn, request: Request):
    ratelimit.enforce(
        ratelimit.client_key(request, "reset"),
        settings.RESET_RATE_LIMIT, settings.RESET_RATE_WINDOW_SEC,
    )
    try:
        supabase_auth.set_new_password(body.recovery_token, body.new_password)
    except supabase_auth.SupabaseAuthError:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired — request a new one.")
    return schemas.MessageOut(message="Password updated — you can now sign in.")


@router.get("/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(auth.get_current_user)):
    return user