import uuid
import datetime as dt
import enum
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, ForeignKey, Text, DateTime, JSON, Date
)
from sqlalchemy.orm import relationship
from .database import Base


def uid() -> str:
    return str(uuid.uuid4())


def now() -> dt.datetime:
    return dt.datetime.utcnow()


class PlanTier(str, enum.Enum):
    ECONOMY = "ECONOMY"     # Default pay-as-you-go (50 KES per note)
    STARTUP = "STARTUP"     # 100 KES
    BASIC = "BASIC"         # 250 KES
    STANDARD = "STANDARD"   # 800 KES
    PREMIUM = "PREMIUM"     # 1199 KES

class PurchaseType(str, enum.Enum):
    PLAN_SUBSCRIPTION = "PLAN_SUBSCRIPTION"
    ECONOMY_NOTE = "ECONOMY_NOTE"        # 50 KES
    SINGLE_DOWNLOAD = "SINGLE_DOWNLOAD"  # 20 KES
    DOWNLOAD_PASS = "DOWNLOAD_PASS"      # 20 KES Weekly Pass
    SINGLE_AI_NOTE = "SINGLE_AI_NOTE"    # 80 KES


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=uid)
    email = Column(String, unique=True, index=True, nullable=False)
    display_name = Column(String, default="")
    plan = Column(String, default=PlanTier.ECONOMY.value)  
    llm_credits = Column(Integer, default=0)
    unlimited_downloads_until = Column(DateTime(timezone=True), nullable=True) # Supports Weekly Download Passes
    
    # NEW: Admin & Demographic Tracking
    is_admin = Column(Boolean, default=False)
    university = Column(String, default="Unknown")
    
    created_at = Column(DateTime, default=now)

    videos = relationship("Video", back_populates="user", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")
    exports = relationship("Export", back_populates="user", cascade="all, delete-orphan")
    
    # New Educational Pillars
    documents = relationship("Document", back_populates="user", cascade="all, delete-orphan")
    diagrams = relationship("InteractiveDiagram", back_populates="user", cascade="all, delete-orphan")
    flashcards = relationship("Flashcard", back_populates="user", cascade="all, delete-orphan")
    
    # Monetization Relationships
    subscription = relationship("UserSubscription", back_populates="user", uselist=False, cascade="all, delete-orphan")
    daily_usages = relationship("DailyUsage", back_populates="user", cascade="all, delete-orphan")
    one_off_credits = relationship("OneOffCredit", back_populates="user", cascade="all, delete-orphan")


class Transaction(Base):
    """Legacy transaction table, kept for backward compatibility."""
    __tablename__ = "transactions"
    id = Column(String, primary_key=True, index=True, default=uid)
    user_id = Column(String, ForeignKey("users.id"))
    amount = Column(Integer)
    plan_name = Column(String)
    status = Column(String, default="pending") 
    created_at = Column(DateTime, default=now)

    user = relationship("User", back_populates="transactions")


# ==========================================
# ADMIN COMMAND CENTER & FINANCIAL LEDGERS
# ==========================================

class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id = Column(String, primary_key=True, default=uid)
    email = Column(String, index=True, nullable=False)
    ip_address = Column(String, nullable=False)
    attempt_time = Column(DateTime, default=now)
    successful = Column(Boolean, default=False)


class FinancialPot(Base):
    __tablename__ = "financial_pots"
    id = Column(String, primary_key=True) # 'maintenance', 'savings', 'scalability', 'emergency', 'shareholders'
    name = Column(String, nullable=False)
    balance = Column(Float, default=0.0)
    borrowed = Column(Float, default=0.0)
    split_percentage = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=now, onupdate=now)


class AdminActionLog(Base):
    __tablename__ = "admin_action_logs"
    id = Column(String, primary_key=True, default=uid)
    admin_id = Column(String, ForeignKey("users.id"), nullable=False)
    action_type = Column(String, nullable=False) # 'BORROW', 'REPAY', 'EXPENSE', 'MONTHLY_ALLOCATION'
    amount = Column(Float, nullable=False)
    source_pot_id = Column(String, ForeignKey("financial_pots.id"), nullable=True)
    target_pot_id = Column(String, ForeignKey("financial_pots.id"), nullable=True)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=now)

class RecurringExpense(Base):
    __tablename__ = "recurring_expenses"
    id = Column(String, primary_key=True, default=uid)
    name = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    interval_days = Column(Integer, nullable=False)
    next_due = Column(DateTime, nullable=False)
    status = Column(String, default="PENDING")
    created_at = Column(DateTime, default=now)


# ==========================================
# MONETIZATION & USAGE TRACKING
# ==========================================

class UserSubscription(Base):
    __tablename__ = "user_subscriptions"
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, unique=True)
    tier = Column(String, default=PlanTier.ECONOMY.value, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=now, onupdate=now)

    user = relationship("User", back_populates="subscription")


class DailyUsage(Base):
    __tablename__ = "daily_usages"
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    usage_date = Column(Date, default=dt.date.today, nullable=False)
    
    youtube_seconds = Column(Integer, default=0)
    ai_notes_count = Column(Integer, default=0)
    static_sims_count = Column(Integer, default=0)
    llm_sims_count = Column(Integer, default=0)
    doc_summaries_count = Column(Integer, default=0)

    user = relationship("User", back_populates="daily_usages")


class ResourceNoteUsage(Base):
    __tablename__ = "resource_note_usages"
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    resource_id = Column(String, nullable=False)  
    ai_gen_attempts = Column(Integer, default=0)
    summary_attempts = Column(Integer, default=0)


class OneOffCredit(Base):
    __tablename__ = "one_off_credits"
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    credit_type = Column(String, nullable=False) 
    is_redeemed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)

    user = relationship("User", back_populates="one_off_credits")


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    merchant_request_id = Column(String, nullable=True)
    checkout_request_id = Column(String, nullable=True)
    phone_number = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    purchase_type = Column(String, nullable=False)
    target_tier = Column(String, nullable=True)
    status = Column(String, default="PENDING") 
    created_at = Column(DateTime, default=now)


# ==========================================
# PILLAR 1: VIDEO CAPTURE (Existing)
# ==========================================

class Video(Base):
    __tablename__ = "videos"
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey("users.id"))
    youtube_id = Column(String, index=True)
    title = Column(String, default="Untitled video")
    channel = Column(String, default="")
    duration_sec = Column(Integer, default=0)
    status = Column(String, default="initializing")
    ai_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=now)

    user = relationship("User", back_populates="videos")
    sessions = relationship("Session", back_populates="video", cascade="all, delete-orphan")
    note_sections = relationship("NoteSection", back_populates="video", cascade="all, delete-orphan")
    exports = relationship("Export", back_populates="video", cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "sessions"
    id = Column(String, primary_key=True, default=uid)
    video_id = Column(String, ForeignKey("videos.id"))
    user_id = Column(String, ForeignKey("users.id"))
    started_at = Column(DateTime, default=now)
    ended_at = Column(DateTime, nullable=True)
    status = Column(String, default="initializing")
    topic_model = Column(JSON, default=dict)

    video = relationship("Video", back_populates="sessions")
    transcript_segments = relationship("TranscriptSegment", back_populates="session", cascade="all, delete-orphan")
    visual_events = relationship("VisualEvent", back_populates="session", cascade="all, delete-orphan")


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    id = Column(String, primary_key=True, default=uid)
    session_id = Column(String, ForeignKey("sessions.id"))
    start_ms = Column(Integer)
    end_ms = Column(Integer)
    text = Column(Text)
    speaker = Column(String, default="speaker_1")
    confidence = Column(Float, default=1.0)
    is_final = Column(Boolean, default=True)
    embedding = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=now)

    session = relationship("Session", back_populates="transcript_segments")


class VisualEvent(Base):
    __tablename__ = "visual_events"
    id = Column(String, primary_key=True, default=uid)
    session_id = Column(String, ForeignKey("sessions.id"))
    timestamp_ms = Column(Integer)
    type = Column(String, default="slide")
    storage_key = Column(String, nullable=True)
    ocr_text = Column(Text, default="")
    description = Column(Text, default="")
    latex = Column(Text, nullable=True)
    salience_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=now)

    session = relationship("Session", back_populates="visual_events")


class NoteSection(Base):
    __tablename__ = "note_sections"
    id = Column(String, primary_key=True, default=uid)
    video_id = Column(String, ForeignKey("videos.id"))
    parent_id = Column(String, ForeignKey("note_sections.id"), nullable=True)
    heading = Column(String, default="")
    body_md = Column(Text, default="")
    order_index = Column(Integer, default=0)
    timestamp_ms = Column(Integer, default=0)
    verification_status = Column(String, default="unverified")
    created_at = Column(DateTime, default=now)

    video = relationship("Video", back_populates="note_sections")
    assets = relationship("NoteAsset", back_populates="section", cascade="all, delete-orphan")


class NoteAsset(Base):
    __tablename__ = "note_assets"
    id = Column(String, primary_key=True, default=uid)
    note_section_id = Column(String, ForeignKey("note_sections.id"))
    asset_type = Column(String, default="image")
    storage_key = Column(String, nullable=True)
    content = Column(Text, nullable=True)

    section = relationship("NoteSection", back_populates="assets")


# ==========================================
# PILLAR 2: DOCU-VISION & SMART READING
# ==========================================

class Document(Base):
    __tablename__ = "documents"
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey("users.id"))
    title = Column(String, default="Untitled Document")
    filename = Column(String, nullable=False)
    storage_key = Column(String, nullable=False)
    status = Column(String, default="processing") 
    ai_summary_md = Column(Text, nullable=True) 
    created_at = Column(DateTime, default=now)

    user = relationship("User", back_populates="documents")
    pages = relationship("DocumentPage", back_populates="document", cascade="all, delete-orphan")
    exports = relationship("Export", back_populates="document", cascade="all, delete-orphan")


class DocumentPage(Base):
    __tablename__ = "document_pages"
    id = Column(String, primary_key=True, default=uid)
    document_id = Column(String, ForeignKey("documents.id"))
    page_number = Column(Integer)
    image_storage_key = Column(String, nullable=False)
    ocr_text = Column(Text, default="")
    ai_analysis = Column(Text, nullable=True) 
    created_at = Column(DateTime, default=now)

    document = relationship("Document", back_populates="pages")


# ==========================================
# PILLAR 3: SPATIAL DIAGRAMS & SIMULATORS
# ==========================================

class InteractiveDiagram(Base):
    __tablename__ = "interactive_diagrams"
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey("users.id"))
    title = Column(String, default="Untitled Diagram")
    sim_type = Column(String, default="custom") 
    canvas_state = Column(JSON, default=dict) 
    prompt_history = Column(JSON, default=list) 
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)

    user = relationship("User", back_populates="diagrams")


# ==========================================
# PILLAR 4: SPACED REPETITION & FLASHCARDS
# ==========================================

class Flashcard(Base):
    __tablename__ = "flashcards"
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey("users.id"))
    source_context = Column(String, nullable=True) 
    front_text = Column(Text, nullable=False)
    back_text = Column(Text, nullable=False)
    
    next_review_at = Column(DateTime, default=now)
    interval_days = Column(Integer, default=0)
    ease_factor = Column(Float, default=2.5)
    repetitions = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=now)

    user = relationship("User", back_populates="flashcards")


# ==========================================
# PILLAR 5: AI KNOWLEDGE GRAPH
# ==========================================

class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey("users.id"))
    concept_name = Column(String, index=True)
    description_md = Column(Text, default="")
    source_references = Column(JSON, default=list) 
    created_at = Column(DateTime, default=now)


class KnowledgeEdge(Base):
    __tablename__ = "knowledge_edges"
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey("users.id"))
    source_node_id = Column(String, ForeignKey("knowledge_nodes.id"))
    target_node_id = Column(String, ForeignKey("knowledge_nodes.id"))
    relationship_type = Column(String, default="related_to") 
    weight = Column(Float, default=1.0)
    created_at = Column(DateTime, default=now)


# ==========================================
# UTILITIES
# ==========================================

class ConsentLog(Base):
    __tablename__ = "consent_log"
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey("users.id"))
    session_id = Column(String, nullable=True)
    consented_at = Column(DateTime, default=now)
    scope = Column(String, default="audio,video,transcript")


class LlmJob(Base):
    __tablename__ = "llm_jobs"
    id = Column(String, primary_key=True, default=uid)
    session_id = Column(String, nullable=True)
    provider = Column(String, default="") 
    model = Column(String)
    purpose = Column(String) 
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    status = Column(String, default="ok")
    latency_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=now)


class Export(Base):
    __tablename__ = "exports"
    id = Column(String, primary_key=True, default=uid)
    video_id = Column(String, ForeignKey("videos.id"), nullable=True)
    document_id = Column(String, ForeignKey("documents.id"), nullable=True)
    user_id = Column(String, ForeignKey("users.id"))
    storage_key = Column(String)
    format = Column(String, default="pdf")
    download_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=now)

    video = relationship("Video", back_populates="exports")
    document = relationship("Document", back_populates="exports")
    user = relationship("User", back_populates="exports")