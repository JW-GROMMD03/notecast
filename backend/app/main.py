import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from .config import settings
from .database import Base, engine

# Active Routers
from .routers import auth as auth_router
from .routers import videos as videos_router
from .routers import notes as notes_router
from .routers import ws as ws_router
from .routers import payments as payments_router
from .routers import diagrams as diagrams_router
from .routers import documents as documents_router
from .routers import flashcards as flashcards_router
from .routers import graph as graph_router

logging.basicConfig(level=logging.INFO)

# Generate all new tables in the SQLite database
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="NoteCast API",
    description="Turns a YouTube watch session and PDFs into verified study notes, interactive simulators, and knowledge graphs.",
    version="2.0.0",
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logging.getLogger("notecast").exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on our end. Please try again."})


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://notecast-web.onrender.com",  # Production Web Frontend
        "chrome-extension://<YOUR_CHROME_EXTENSION_ID_HERE>" 
    ] + settings.cors_origin_list, 
    allow_credentials=True, 
    allow_methods=["*"],
    allow_headers=["*"],
)

# Local-disk media (frames, exports, pdf uploads)
app.mount("/media", StaticFiles(directory=str(settings.storage_path)), name="media")

# Active Routers
app.include_router(auth_router.router)
app.include_router(videos_router.router)
app.include_router(notes_router.router)
app.include_router(ws_router.router)
app.include_router(payments_router.router)
app.include_router(diagrams_router.router)
app.include_router(documents_router.router)
app.include_router(flashcards_router.router)
app.include_router(graph_router.router)


@app.get("/health")
def health():
    return {"status": "ok", "version": "2.0.0-interactive"}