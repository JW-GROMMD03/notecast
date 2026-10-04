from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

if not settings.DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Copy it from your Supabase project: "
        "Project Settings -> Database -> Connection string -> URI (Session pooler tab), "
        "and put it in backend/.env as DATABASE_URL=postgresql://... "
        "(This app no longer falls back to a local SQLite file, since it's built "
        "around Supabase for both auth and data.)"
    )

# For local/offline testing without a real Supabase project, you can still
# point DATABASE_URL at sqlite:///./notecast.db — the check above only
# blocks an *empty* value, not sqlite specifically. Just note that Supabase
# Auth (signup/login/etc.) is a separate, always-remote dependency and
# won't work without a real project regardless of what DATABASE_URL is.
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
