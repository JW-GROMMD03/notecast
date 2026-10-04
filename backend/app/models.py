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
    # This id IS the Supabase auth.users.id (UUID, as text) — never
    # generated locally, always taken from the verified JWT's `sub` claim.
    # Supabase owns the credential (password hash, reset tokens, etc.);
    # this table is purely app-level profile data.
    id = Column(String, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    display_name = Column(String, default="")
    plan = Column(String, default="free")  # free | pro
    llm_credits = Column(Integer, default=0)
    created_at = Column(DateTime, default=now)

    videos = relationship("Video", back_populates="user", cascade="all, delete-orphan")


class ConsentLog(Base):
    __tablename__ = "consent_log"
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey("users.id"))
    session_id = Column(String, nullable=True)
    consented_at = Column(DateTime, default=now)
    scope = Column(String, default="audio,video,transcript")


class Video(Base):
    __tablename__ = "videos"
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey("users.id"))
    youtube_id = Column(String, index=True)
    title = Column(String, default="Untitled video")
    channel = Column(String, default="")
    duration_sec = Column(Integer, default=0)
    status = Column(String, default="initializing")
    # initializing -> capturing -> processing -> completed -> failed
    
    # Stores the generated master study guide markdown content
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
    topic_model = Column(JSON, default=dict)  # domain, key terms, vocab hints

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
    embedding = Column(JSON, nullable=True)  # list[float], used for claim verification
    created_at = Column(DateTime, default=now)

    session = relationship("Session", back_populates="transcript_segments")


class VisualEvent(Base):
    __tablename__ = "visual_events"
    id = Column(String, primary_key=True, default=uid)
    session_id = Column(String, ForeignKey("sessions.id"))
    timestamp_ms = Column(Integer)
    type = Column(String, default="slide")  # diagram | code | slide | chart | whiteboard
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
    verification_status = Column(String, default="unverified")  # unverified|accepted|repaired|rejected
    created_at = Column(DateTime, default=now)

    video = relationship("Video", back_populates="note_sections")
    assets = relationship("NoteAsset", back_populates="section", cascade="all, delete-orphan")


class NoteAsset(Base):
    __tablename__ = "note_assets"
    id = Column(String, primary_key=True, default=uid)
    note_section_id = Column(String, ForeignKey("note_sections.id"))
    asset_type = Column(String, default="image")  # image|latex|code
    storage_key = Column(String, nullable=True)
    content = Column(Text, nullable=True)  # for latex/code

    section = relationship("NoteSection", back_populates="assets")


class LlmJob(Base):
    __tablename__ = "llm_jobs"
    id = Column(String, primary_key=True, default=uid)
    session_id = Column(String, nullable=True)
    provider = Column(String, default="")  # set per-call to whichever of gemini/groq/deepseek actually served it
    model = Column(String)
    purpose = Column(String)  # asr|vision|note_draft|reorganize|enrich|verify|embed
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    status = Column(String, default="ok")
    latency_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=now)


class Export(Base):
    __tablename__ = "exports"
    id = Column(String, primary_key=True, default=uid)
    video_id = Column(String, ForeignKey("videos.id"))
    user_id = Column(String, ForeignKey("users.id"))
    storage_key = Column(String)
    format = Column(String, default="pdf")
    download_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=now)

    video = relationship("Video", back_populates="exports")