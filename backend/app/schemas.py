from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
import datetime as dt

# --- AUTH & USERS ---
class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: Optional[str] = ""

class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

class RefreshIn(BaseModel):
    refresh_token: Optional[str] = None

class ForgotPasswordIn(BaseModel):
    email: EmailStr

class ResetPasswordIn(BaseModel):
    recovery_token: str
    new_password: str = Field(min_length=8, max_length=128)

class MessageOut(BaseModel):
    message: str

class SessionTokensOut(BaseModel):
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
    class Config: from_attributes = True

# --- PAYMENTS ---
class PaymentRequest(BaseModel):
    phone_number: str
    plan_name: str
    amount: int

class PaymentStatusOut(BaseModel):
    status: str

# --- VIDEOS & NOTES ---
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
    class Config: from_attributes = True

class ConsentIn(BaseModel):
    session_id: Optional[str] = None
    scope: str = "audio,video,transcript"

class SessionOut(BaseModel):
    id: str
    video_id: str
    status: str
    topic_model: dict
    class Config: from_attributes = True

class TranscriptSegmentOut(BaseModel):
    id: str
    start_ms: int
    end_ms: int
    text: str
    speaker: str
    confidence: float
    is_final: bool
    class Config: from_attributes = True

class VisualEventOut(BaseModel):
    id: str
    timestamp_ms: int
    type: str
    storage_key: Optional[str]
    description: str
    ocr_text: str
    latex: Optional[str]
    class Config: from_attributes = True

class NoteAssetOut(BaseModel):
    id: str
    asset_type: str
    storage_key: Optional[str]
    content: Optional[str]
    class Config: from_attributes = True

class NoteSectionOut(BaseModel):
    id: str
    parent_id: Optional[str]
    heading: str
    body_md: str
    order_index: int
    timestamp_ms: int
    verification_status: str
    assets: List[NoteAssetOut] = []
    class Config: from_attributes = True

class ExportOut(BaseModel):
    id: str
    format: str
    storage_key: str
    download_count: int
    created_at: dt.datetime
    class Config: from_attributes = True


# ==========================================
# NEW PILLARS: SCHEMAS
# ==========================================

# --- DOCU-VISION ---
class DocumentOut(BaseModel):
    id: str
    title: str
    filename: str
    status: str
    created_at: dt.datetime
    class Config: from_attributes = True

class DocumentPageOut(BaseModel):
    id: str
    page_number: int
    image_storage_key: str
    ocr_text: str
    ai_analysis: Optional[str]
    class Config: from_attributes = True

# --- SPATIAL DIAGRAMS & SIMS ---
class InteractiveDiagramCreateIn(BaseModel):
    title: str
    sim_type: str = "custom"
    prompt: Optional[str] = None # If user wants AI to generate the initial canvas

class InteractiveDiagramUpdateIn(BaseModel):
    canvas_state: Dict[str, Any]

class InteractiveDiagramOut(BaseModel):
    id: str
    title: str
    sim_type: str
    canvas_state: Dict[str, Any]
    updated_at: dt.datetime
    class Config: from_attributes = True

# --- FLASHCARDS ---
class FlashcardOut(BaseModel):
    id: str
    source_context: Optional[str]
    front_text: str
    back_text: str
    next_review_at: dt.datetime
    class Config: from_attributes = True

class FlashcardReviewIn(BaseModel):
    quality: int = Field(ge=0, le=5) # 0=Blackout, 5=Perfect recall (SM-2 standard)

# --- KNOWLEDGE GRAPH ---
class KnowledgeNodeOut(BaseModel):
    id: str
    concept_name: str
    description_md: str
    source_references: List[str]
    class Config: from_attributes = True

class KnowledgeEdgeOut(BaseModel):
    id: str
    source_node_id: str
    target_node_id: str
    relationship_type: str
    weight: float
    class Config: from_attributes = True


class KnowledgeNodeCreateIn(BaseModel):
    concept_name: str
    description_md: str = ""
    source_references: List[str] = []

class KnowledgeEdgeCreateIn(BaseModel):
    source_node_id: str
    target_node_id: str
    relationship_type: str = "related_to"
    weight: float = 1.0