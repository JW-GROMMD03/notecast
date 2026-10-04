from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
import datetime as dt


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: Optional[str] = ""


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)  # no min-length here: don't help an attacker learn the policy from error text


class RefreshIn(BaseModel):
    # Only used by the extension (Bearer mode) — the web app's refresh
    # token travels in an httpOnly cookie and never appears in a body.
    refresh_token: Optional[str] = None


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    recovery_token: str
    new_password: str = Field(min_length=8, max_length=128)


class MessageOut(BaseModel):
    message: str


class SessionTokensOut(BaseModel):
    """Returned in the response body on login/refresh so the extension can
    store these in chrome.storage.local. The web app ignores this body
    entirely — its session lives in the httpOnly cookies set alongside it."""
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"
    user_id: str
    email: str
    display_name: str


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    plan: str

    class Config:
        from_attributes = True


class VideoCreateIn(BaseModel):
    youtube_id: str
    title: str
    channel: str = ""
    duration_sec: int = 0


class VideoOut(BaseModel):
    id: str
    youtube_id: str
    title: str
    channel: str
    duration_sec: int
    status: str
    created_at: dt.datetime

    class Config:
        from_attributes = True


class ConsentIn(BaseModel):
    session_id: Optional[str] = None
    scope: str = "audio,video,transcript"


class SessionOut(BaseModel):
    id: str
    video_id: str
    status: str
    topic_model: dict

    class Config:
        from_attributes = True


class TranscriptSegmentOut(BaseModel):
    id: str
    start_ms: int
    end_ms: int
    text: str
    speaker: str
    confidence: float
    is_final: bool

    class Config:
        from_attributes = True


class VisualEventOut(BaseModel):
    id: str
    timestamp_ms: int
    type: str
    storage_key: Optional[str]
    description: str
    ocr_text: str
    latex: Optional[str]

    class Config:
        from_attributes = True


class NoteAssetOut(BaseModel):
    id: str
    asset_type: str
    storage_key: Optional[str]
    content: Optional[str]

    class Config:
        from_attributes = True


class NoteSectionOut(BaseModel):
    id: str
    parent_id: Optional[str]
    heading: str
    body_md: str
    order_index: int
    timestamp_ms: int
    verification_status: str
    assets: List[NoteAssetOut] = []

    class Config:
        from_attributes = True


class ExportOut(BaseModel):
    id: str
    format: str
    storage_key: str
    download_count: int
    created_at: dt.datetime

    class Config:
        from_attributes = True
