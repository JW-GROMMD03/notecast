import uuid
import datetime as dt
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, ForeignKey, Text, DateTime, JSON
)
from sqlalchemy.orm import relationship
from .database import Base


def uid() -> str:
    return str(uuid.uuid4())


def now() -> dt.datetime:
    return dt.datetime.utcnow()


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    display_name = Column(String, default="")
    plan = Column(String, default="free")  # free | pro | weekly | monthly
    llm_credits = Column(Integer, default=0)
    created_at = Column(DateTime, default=now)

    videos = relationship("Video", back_populates="user", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")
    
    # New Educational Pillars
    documents = relationship("Document", back_populates="user", cascade="all, delete-orphan")
    diagrams = relationship("InteractiveDiagram", back_populates="user", cascade="all, delete-orphan")
    flashcards = relationship("Flashcard", back_populates="user", cascade="all, delete-orphan")


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"))
    amount = Column(Integer)
    plan_name = Column(String)
    status = Column(String, default="pending") 
    created_at = Column(DateTime, default=now)

    user = relationship("User", back_populates="transactions")


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
    status = Column(String, default="processing") # processing -> ready -> failed
    ai_summary_md = Column(Text, nullable=True) # The synthesized, gap-filled study guide
    created_at = Column(DateTime, default=now)

    user = relationship("User", back_populates="documents")
    pages = relationship("DocumentPage", back_populates="document", cascade="all, delete-orphan")


class DocumentPage(Base):
    __tablename__ = "document_pages"
    id = Column(String, primary_key=True, default=uid)
    document_id = Column(String, ForeignKey("documents.id"))
    page_number = Column(Integer)
    image_storage_key = Column(String, nullable=False)
    ocr_text = Column(Text, default="")
    ai_analysis = Column(Text, nullable=True) # Specifically extracts charts, removes fluff
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
    sim_type = Column(String, default="custom") # custom | load_balancer | circuit | chemistry
    canvas_state = Column(JSON, default=dict) # Stores node/edge JSON for vector rendering
    prompt_history = Column(JSON, default=list) # Stores the prompts used to generate/modify it
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)

    user = relationship("User", back_populates="diagrams")


# ==========================================
# PILLAR 4: SPACED REPETITION & FLASHCARDS
# ==========================================

class Flashcard(Base):
    """Implements SuperMemo-2 (SM-2) or similar spaced repetition algorithm tracking."""
    __tablename__ = "flashcards"
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey("users.id"))
    source_context = Column(String, nullable=True) # e.g., "Video: Load Balancing"
    front_text = Column(Text, nullable=False)
    back_text = Column(Text, nullable=False)
    
    # Spaced Repetition Tracking
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
    source_references = Column(JSON, default=list) # Links back to Video IDs or Document IDs
    created_at = Column(DateTime, default=now)


class KnowledgeEdge(Base):
    __tablename__ = "knowledge_edges"
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey("users.id"))
    source_node_id = Column(String, ForeignKey("knowledge_nodes.id"))
    target_node_id = Column(String, ForeignKey("knowledge_nodes.id"))
    relationship_type = Column(String, default="related_to") # prerequisite_for, part_of, related_to
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