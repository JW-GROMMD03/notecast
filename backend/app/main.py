import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

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
from .routers.admin import router as admin_router # DIRECT IMPORT

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
        "https://notecast-web.onrender.com",
    ] + settings.cors_origin_list, 
    allow_credentials=True, 
    allow_methods=["*"],
    allow_headers=["*"],
)

# Local-disk media mount
app.mount("/media", StaticFiles(directory=str(settings.storage_path)), name="media")

# Active Routers Registration
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
app.include_router(admin_router)

@app.get("/health")
def health():
    return {"status": "ok", "version": "2.1.0-socratic"}