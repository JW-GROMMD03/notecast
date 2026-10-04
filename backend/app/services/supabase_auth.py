"""
Thin client for Supabase's Auth REST API (GoTrue) plus JWT verification.
Includes Admin SDK methods to generate links for third-party email handling (Resend).
"""
import time
import httpx
from jose import jwt, JWTError

from ..config import settings


class SupabaseAuthError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _headers(bearer: str | None = None) -> dict:
    h = {"apikey": settings.SUPABASE_ANON_KEY, "Content-Type": "application/json"}
    if bearer:
        h["Authorization"] = f"Bearer {bearer}"
    return h


def _base() -> str:
    if not settings.SUPABASE_URL or not settings.SUPABASE_ANON_KEY:
        raise SupabaseAuthError("Auth is not configured on the server.", 500)
    return settings.SUPABASE_URL.rstrip("/") + "/auth/v1"


def _request(method: str, path: str, bearer: str | None = None, json_body: dict | None = None) -> dict:
    try:
        resp = httpx.request(method, f"{_base()}{path}", headers=_headers(bearer), json=json_body, timeout=10.0)
    except httpx.RequestError as e:
        raise SupabaseAuthError("Could not reach the authentication service. Try again shortly.", 503) from e

    if resp.status_code >= 400:
        try: detail = resp.json()
        except ValueError: detail = {}
        raise SupabaseAuthError(detail.get("msg") or detail.get("error_description") or detail.get("error") or "Request failed", resp.status_code)

    return resp.json() if resp.content else {}


def _admin_request(method: str, path: str, json_body: dict | None = None) -> dict:
    if not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise SupabaseAuthError("Server is missing SUPABASE_SERVICE_ROLE_KEY in .env", 500)
    
    headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json"
    }
    try:
        resp = httpx.request(method, f"{_base()}{path}", headers=headers, json=json_body, timeout=10.0)
    except httpx.RequestError as e:
        raise SupabaseAuthError("Could not reach the auth service.", 503) from e

    if resp.status_code >= 400:
        try: detail = resp.json()
        except ValueError: detail = {}
        raise SupabaseAuthError(detail.get("msg") or detail.get("error") or "Request failed", resp.status_code)
    return resp.json() if resp.content else {}


# ---------------------------------------------------------------------------
# Identity operations (Admin generation for Resend dispatch)
# ---------------------------------------------------------------------------

def generate_signup_link(email: str, password: str, display_name: str) -> dict:
    return _admin_request("POST", "/admin/generate_link", json_body={
        "type": "signup",
        "email": email,
        "password": password,
        "data": {"display_name": display_name},
        "redirect_to": "http://127.0.0.1:5501/web/login.html"
    })


def generate_recovery_link(email: str) -> str:
    res = _admin_request("POST", "/admin/generate_link", json_body={
        "type": "recovery",
        "email": email,
        "redirect_to": "http://127.0.0.1:5501/web/reset-password.html"
    })
    properties = res.get("properties", {})
    return properties.get("action_link") or res.get("action_link", "")


def sign_in_with_password(email: str, password: str) -> dict:
    return _request("POST", "/token?grant_type=password", json_body={"email": email, "password": password})

def refresh_session(refresh_token: str) -> dict:
    return _request("POST", "/token?grant_type=refresh_token", json_body={"refresh_token": refresh_token})

def sign_out(access_token: str) -> None:
    try: _request("POST", "/logout", bearer=access_token)
    except SupabaseAuthError: pass

def set_new_password(recovery_access_token: str, new_password: str) -> None:
    _request("PUT", "/user", bearer=recovery_access_token, json_body={"password": new_password})

def get_user(access_token: str) -> dict:
    """Fetches and verifies the user profile from Supabase using an access token."""
    return _request("GET", "/user", bearer=access_token)

# ---------------------------------------------------------------------------
# JWT verification
# ---------------------------------------------------------------------------

_JWKS = None
def _get_jwks() -> dict:
    global _JWKS
    if _JWKS is None:
        try:
            jwks_url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
            resp = httpx.get(jwks_url, headers=_headers(), timeout=10.0)
            resp.raise_for_status()
            _JWKS = resp.json()
        except Exception as e:
            raise SupabaseAuthError("Could not retrieve Supabase public keys.", 500) from e
    return _JWKS

def verify_access_token(token: str) -> dict:
    try:
        unverified_header = jwt.get_unverified_header(token)
        alg = unverified_header.get("alg")

        if alg == "HS256":
            claims = jwt.decode(token, settings.SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated")
        elif alg in ["RS256", "ES256"]:
            claims = jwt.decode(token, _get_jwks(), algorithms=[alg], audience="authenticated")
        else:
            raise SupabaseAuthError(f"Unsupported JWT algorithm: {alg}", 401)
        
        if claims.get("exp", 0) < time.time():
            raise SupabaseAuthError("Session expired or invalid.", 401)
            
        return claims
    except JWTError as e:
        raise SupabaseAuthError("Session expired or invalid.", 401) from e