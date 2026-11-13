# main.py
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
import os

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

# Generate all tables in SQLite / PostgreSQL
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="NoteCast API",
    description="Turns a YouTube watch session and PDFs into verified study notes, interactive simulators, and Socratic voice coaching.",
    version="2.1.0",
)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logging.getLogger("notecast").exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on our end. Please try again."})

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://notecast-53sj.onrender.com",
        "https://notecast-web.onrender.com",
    ] + settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- STATIC ASSETS & MEDIA MOUNTS ---
app.mount("/assets", StaticFiles(directory="web/assets"), name="assets")
app.mount("/simulations", StaticFiles(directory="web/simulations"), name="simulations")
app.mount("/media", StaticFiles(directory=str(settings.storage_path)), name="media")

# --- CLEAN URL HTML ROUTE HANDLERS ---
@app.get("/")
def serve_index():
    return FileResponse("web/index.html")

@app.get("/dashboard")
def serve_dashboard():
    return FileResponse("web/dashboard/index.html")

@app.get("/login")
def serve_login():
    return FileResponse("web/login/index.html")

@app.get("/signup")
def serve_signup():
    return FileResponse("web/signup/index.html")

@app.get("/payments")
def serve_payments():
    return FileResponse("web/payments/index.html")

@app.get("/video")
def serve_video():
    return FileResponse("web/video/index.html")

@app.get("/simulator")
def serve_simulator():
    return FileResponse("web/simulator/index.html")

@app.get("/reader")
def serve_reader():
    return FileResponse("web/reader/index.html")

@app.get("/contact")
def serve_contact():
    return FileResponse("web/contact/index.html")

@app.get("/terms")
def serve_terms():
    return FileResponse("web/terms/index.html")

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