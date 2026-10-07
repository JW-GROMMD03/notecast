"""
Authentication dependencies and cookie/CSRF plumbing with TRACE LOGGING.
"""
import secrets
import datetime as dt
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session as DbSession

from .config import settings
from .database import get_db
from . import models
from .services import supabase_auth


def _extract_token(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[len("Bearer "):].strip()
    return request.cookies.get(settings.ACCESS_COOKIE_NAME)


def get_current_user(request: Request, db: DbSession = Depends(get_db)) -> models.User:
    print("\n" + "="*50)
    print("🔍 AUTH TRACE: /auth/me called")
    print(f"-> All cookies received from browser: {request.cookies.keys()}")
    
    token = _extract_token(request)
    if not token:
        print("❌ REJECTED: access token cookie is completely missing!")
        print("="*50 + "\n")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        
    print(f"-> Access token extracted (starts with: {token[:15]}...)")
    
    try:
        claims = supabase_auth.verify_access_token(token)
        print("-> Token cryptographic signature verified successfully.")
    except supabase_auth.SupabaseAuthError as e:
        print(f"❌ REJECTED by verify_access_token: {e.message}")
        print("="*50 + "\n")
        raise HTTPException(status_code=401, detail=e.message)
    except Exception as e:
        print(f"❌ UNEXPECTED ERROR during verification: {str(e)}")
        print("="*50 + "\n")
        raise HTTPException(status_code=401, detail="Internal verify error")

    user_id = claims.get("sub")
    if not user_id:
        print("❌ REJECTED: Token is valid but has no 'sub' (user_id) claim!")
        print("="*50 + "\n")
        raise HTTPException(status_code=401, detail="Invalid token structure")

    print(f"-> Looking up user in database: {user_id}")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    
    if not user:
        print("-> User not in local DB yet. Creating profile row...")
        user = models.User(
            id=user_id, 
            email=claims.get("email", ""), 
            display_name=claims.get("user_metadata", {}).get("display_name", "")
        )
        try:
            db.add(user)
            db.commit()
            db.refresh(user)
            print("-> Local profile created successfully.")
        except Exception as e:
            print(f"❌ DATABASE ERROR creating user: {str(e)}")
            db.rollback()
            print("="*50 + "\n")
            raise HTTPException(status_code=500, detail="Could not create local profile")
            
    print("✅ AUTH SUCCESS: User granted access to dashboard!")
    print("="*50 + "\n")
    return user


def get_current_user_ws(token: str, db: DbSession) -> models.User | None:
    try:
        claims = supabase_auth.verify_access_token(token)
    except supabase_auth.SupabaseAuthError:
        return None
    return db.query(models.User).filter(models.User.id == claims.get("sub")).first()


def issue_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def verify_csrf(request: Request) -> None:
    if request.headers.get("Authorization", "").startswith("Bearer "):
        return
    cookie_token = request.cookies.get(settings.CSRF_COOKIE_NAME)
    header_token = request.headers.get(settings.CSRF_HEADER_NAME)
    if not cookie_token or not header_token or not secrets.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")


def set_session_cookies(response: Response, access_token: str, refresh_token: str, expires_in: int) -> None:
    common = dict(
        httponly=True,
        secure=settings.COOKIE_SECURE, 
        samesite="none" if settings.COOKIE_SECURE else "lax", 
        domain=settings.COOKIE_DOMAIN or None,
        path="/",
    )
    
    print("\n-> Setting fresh cookies on response")
    response.set_cookie(settings.ACCESS_COOKIE_NAME, access_token, max_age=expires_in, **common)
    response.set_cookie(settings.REFRESH_COOKIE_NAME, refresh_token, max_age=60 * 60 * 24 * 30, **common)
    
    response.set_cookie(
        settings.CSRF_COOKIE_NAME, issue_csrf_token(),
        max_age=60 * 60 * 24 * 30, httponly=False,
        secure=settings.COOKIE_SECURE, samesite="none" if settings.COOKIE_SECURE else "lax",
        domain=settings.COOKIE_DOMAIN or None, path="/",
    )


def clear_session_cookies(response: Response) -> None:
    common = dict(
        domain=settings.COOKIE_DOMAIN or None, 
        path="/",
        samesite="none" if settings.COOKIE_SECURE else "lax",
        secure=settings.COOKIE_SECURE
    )
    for name in (settings.ACCESS_COOKIE_NAME, settings.REFRESH_COOKIE_NAME, settings.CSRF_COOKIE_NAME):
        response.delete_cookie(name, **common)