import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from .config import settings
from .database import Base, engine
from .routers import auth as auth_router
from .routers import videos as videos_router
from .routers import notes as notes_router
from .routers import ws as ws_router

logging.basicConfig(level=logging.INFO)

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="NoteCast API",
    description="Turns a YouTube watch session into verified, exportable study notes.",
    version="1.0.0",
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Without this, an unhandled error's response is built outside the CORS
    # middleware and comes back with no CORS headers at all — the browser
    # then reports it as a generic "Failed to fetch" / CORS error, which is
    # indistinguishable from an actual CORS misconfiguration. This ensures
    # every error, expected or not, at least reaches the frontend as a
    # real, readable response — and the full traceback still prints to
    # this terminal either way.
    logging.getLogger("notecast").exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on our end. Please try again."})

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://jw-grommd03.github.io",  # GitHub Pages Web Frontend
        "chrome-extension://<YOUR_CHROME_EXTENSION_ID_HERE>" # Update this when publishing to the store
    ] + settings.cors_origin_list, 
    allow_credentials=True,  # lets the browser send/receive the httpOnly session cookies
    allow_methods=["*"],
    allow_headers=["*"],
)

# Local-disk media (frames, exports) — swap for CDN/R2 URLs in production.
app.mount("/media", StaticFiles(directory=str(settings.storage_path)), name="media")

app.include_router(auth_router.router)
app.include_router(videos_router.router)
app.include_router(notes_router.router)
app.include_router(ws_router.router)


@app.get("/health")
def health():
    return {"status": "ok"}