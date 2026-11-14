# backend/app/main.py
import logging
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse

from .config import settings
from .database import Base, engine

# Bypass __init__.py and import directly from the router modules
from .routers.auth import router as auth_router
from .routers.videos import router as videos_router
from .routers.notes import router as notes_router
from .routers.ws import router as ws_router
from .routers.payments import router as payments_router
from .routers.diagrams import router as diagrams_router
from .routers.documents import router as documents_router
from .routers.flashcards import router as flashcards_router
from .routers.graph import router as graph_router
from .routers.socratic import router as socratic_router
from .routers.admin import router as admin_router, direct_router as admin_direct_router
from .routers.books import router as books_router
from .routers.referrals import router as referrals_router

# Safely attempt to import the fallback router without crashing if it doesn't exist
try:
    from .routers.referrals import admin_fallback_router as referrals_admin_fallback_router
    HAS_REF_ADMIN = True
except ImportError:
    HAS_REF_ADMIN = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("notecast")

# Resolve absolute project root path dynamically:
# backend/app/main.py -> backend/app -> backend -> project_root
BASE_DIR = Path(__file__).resolve().parent.parent.parent
WEB_DIR = BASE_DIR / "web"
ASSETS_DIR = WEB_DIR / "assets"
SIMULATIONS_DIR = WEB_DIR / "simulations"
MEDIA_DIR = Path(settings.storage_path).resolve()

# Ensure required static directories exist on startup so StaticFiles never raises RuntimeError
for directory in (WEB_DIR, ASSETS_DIR, SIMULATIONS_DIR, MEDIA_DIR):
    directory.mkdir(parents=True, exist_ok=True)

# Generate all tables in SQLite / PostgreSQL
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="NoteCast API",
    description="Turns a YouTube watch session and PDFs into verified study notes, interactive simulators, and Socratic voice coaching.",
    version="2.1.0",
)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on our end. Please try again."})

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://notecast.co.ke",
        "https://www.notecast.co.ke",
        "https://notecast-53sj.onrender.com",
        "https://notecast-web.onrender.com",
    ] + settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- STATIC ASSETS & MEDIA MOUNTS ---
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")
app.mount("/simulations", StaticFiles(directory=str(SIMULATIONS_DIR)), name="simulations")
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")


def _serve_html(relative_path: str) -> FileResponse:
    """Safely serves an HTML page from WEB_DIR with a clean 404 fallback if missing."""
    file_path = WEB_DIR / relative_path
    if not file_path.is_file():
        logger.warning("Requested HTML page not found: %s", file_path)
        raise HTTPException(status_code=404, detail="Page not found.")
    return FileResponse(str(file_path))


# --- CLEAN URL HTML ROUTE HANDLERS ---
@app.get("/")
def serve_index():
    return _serve_html("index.html")

@app.get("/dashboard")
def serve_dashboard():
    return _serve_html("dashboard/index.html")

@app.get("/login")
def serve_login():
    return _serve_html("login/index.html")

@app.get("/signup")
def serve_signup():
    return _serve_html("signup/index.html")

@app.get("/payments")
def serve_payments():
    return _serve_html("payments/index.html")

@app.get("/video")
def serve_video():
    return _serve_html("video/index.html")

@app.get("/simulator")
def serve_simulator():
    return _serve_html("simulator/index.html")

@app.get("/reader")
def serve_reader():
    return _serve_html("reader/index.html")

@app.get("/contact")
def serve_contact():
    return _serve_html("contact/index.html")

@app.get("/terms")
def serve_terms():
    return _serve_html("terms/index.html")


# --- ACTIVE ROUTERS REGISTRATION ---
app.include_router(auth_router)
app.include_router(videos_router)
app.include_router(notes_router)
app.include_router(ws_router)
app.include_router(payments_router)
app.include_router(diagrams_router)
app.include_router(documents_router)
app.include_router(flashcards_router)
app.include_router(graph_router)
app.include_router(socratic_router)
app.include_router(admin_router)          # /admin/...      
app.include_router(admin_direct_router)   # /api/admin/...  

# Referrals & Books 
app.include_router(referrals_router)
if HAS_REF_ADMIN:
    app.include_router(referrals_admin_fallback_router)

app.include_router(books_router)
app.include_router(books_router, prefix="/api")

@app.get("/health")
def health():
    return {"status": "ok", "version": "2.1.0-socratic"}