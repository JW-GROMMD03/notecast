# NoteCast

Turns a YouTube video you're watching into a live transcript, captured diagrams/slides,
and a verified, exportable PDF of study notes. Featuring built-in **M-Pesa STK Push** payment flows and cross-domain Supabase authentication.

This is a working, self-hostable implementation of the NoteCast architecture: a Chrome
extension for capture + a FastAPI backend for transcription, vision analysis, note
generation, hallucination-checking, PDF export, and automated billing.

## What's different from the original cloud-native design

The original design spec called for Supabase, Cloudflare R2, Upstash Redis, Qdrant,
BullMQ, and a choice of ASR/vision providers with circuit breakers — a real multi-service
production stack. Standing all of that up needs cloud accounts and credentials only you
can provide, so this build keeps the same **data model and pipeline phases** but runs
them on infrastructure that works out of the box:

| Original design | This build | Why |
|---|---|---|
| Supabase (Postgres + Auth + Realtime) | FastAPI + SQLAlchemy + SQLite, JWT auth, WebSocket push | No external account needed; swap `DATABASE_URL` for Postgres any time — the models don't change |
| Cloudflare R2 / S3 | Local disk under `backend/storage/`, served at `/media` | Same `storage_key` abstraction (`app/services/storage.py`) — reimplement 3 functions against boto3 to move to R2/S3 |
| Upstash Redis + BullMQ workers | In-process `BackgroundTasks` (`app/workers/pipeline.py`) | Right-sized for a single server; the pipeline functions are already separated so moving them to Celery/RQ later is a lift-and-shift |
| Qdrant vector DB | Embeddings stored per transcript segment, brute-force cosine similarity in `app/services/verify.py` | Fast enough at "a few thousand segments per video" scale; swap for Qdrant if you're running this across many users |
| Deepgram Nova-3 streaming ASR | Gemini/Groq (free Whisper-large-v3) on ~5s buffered audio windows (`app/services/asr.py`) | True sub-second streaming ASR needs a paid streaming provider account; this is "near-live" captions instead of word-by-word |
| MobileNetV3 ONNX salience classifier | A cheap numpy frame-diff + edge-density heuristic (`app/services/vision.py`) | No trained model file to ship; swap in a real ONNX model behind the same `should_capture()` signature |
| Provider fallback with circuit breakers | Three free/near-free providers tried in order — **Gemini → Groq → DeepSeek** — implemented in `app/services/providers.py` | This *is* implemented as specified, just across free-tier providers instead of paid ones. If the first provider is unconfigured, rate-limited, or errors, the next one in the order is used automatically — no manual intervention needed |

Every other phase from the design doc is implemented as specified: consent gate, topic
model priming, two-tier ASR, frame salience gating, incremental 30s note drafting,
post-video reorganize → enrich → verify passes, PDF export with timestamped links
back to the video, and M-Pesa STK Push subscription activations.

## AI providers — three, with automatic fallover

Rather than a single paid API key, NoteCast is wired to three providers and tries them
in order per capability, falling over automatically on any error (missing key, rate
limit, timeout, model retired, etc.) — see `app/services/providers.py`.

| Provider | Free tier? | Used for | Get a key |
|---|---|---|---|
| **Gemini** (`gemini-2.0-flash`) | Yes — generous free tier | Text, vision, audio transcription, embeddings | https://aistudio.google.com/apikey |
| **Groq** (Llama 3.3 / Llama vision / Whisper-large-v3) | Yes — free tier, and the only free Whisper here | Text, vision, audio transcription | https://console.groq.com/keys |
| **DeepSeek** (`deepseek-chat`) | No, but extremely cheap pay-as-you-go | Text only (no vision/audio/embedding API) | https://platform.deepseek.com/api_keys |

You only *need* one key to run the app — `GEMINI_API_KEY` alone covers every
capability. Adding Groq and DeepSeek on top just means a single provider hitting its
daily free-tier limit doesn't take the app down; the next one in line picks up
automatically. Reorder or drop providers per capability in `.env` via
`TEXT_PROVIDER_ORDER` / `VISION_PROVIDER_ORDER` / `ASR_PROVIDER_ORDER` /
`EMBED_PROVIDER_ORDER`.

## Project layout

```text
notecast/
├── backend/
│   ├── .env                    # Environment variables (Supabase keys, Resend API key)
│   ├── requirements.txt        # Python dependencies (fastapi, uvicorn, httpx, jose, etc.)
│   ├── notecast.db             # Local SQLite database
│   ├── .venv/                  # Python virtual environment
│   └── app/
│       ├── __init__.py
│       ├── main.py             # FastAPI app entry point, CORS middleware, and router mounts
│       ├── config.py           # Pydantic Settings configuration (reads .env, CORS)
│       ├── database.py         # SQLAlchemy database session management
│       ├── models.py           # SQLAlchemy database models (User, Video, Transaction, etc.)
│       ├── schemas.py          # Pydantic request/response validation models (Auth, Payments, Videos)
│       ├── auth.py             # JWT verification, httpOnly cross-domain cookie management, and CSRF protection
│       ├── routers/
│       │   ├── __init__.py
│       │   ├── auth.py         # Authentication endpoints (/signup, /login, /oauth-callback, /me, /refresh, /logout)
│       │   ├── payments.py     # M-Pesa Daraja STK push initiation, polling status, and webhooks
│       │   ├── videos.py       # Video capture management routes
│       │   ├── notes.py        # Study notes generation endpoints
│       │   └── ws.py           # WebSocket connection handling for live capture
│       ├── services/
│       │   ├── __init__.py
│       │   ├── supabase_auth.py # GoTrue REST client & Admin SDK link generation
│       │   ├── ratelimit.py    # IP and endpoint rate-limiting service
│       │   ├── pdf.py          # PDF generation tools
│       │   ├── providers.py    # Multi-LLM provider routing (Gemini, Groq, DeepSeek)
│       │   ├── storage.py      # File and asset storage utilities
│       │   ├── verify.py       # Verification utilities
│       │   └── vision.py       # Vision and frame capture services
│       ├── templates/          # HTML templates folder for PDFs
│       └── workers/            # Background background execution workers
├── extension/          # Chrome extension (Manifest V3)
│   ├── background.js     # Owns the WebSocket, orchestrates capture
│   ├── offscreen.js      # Tab-audio capture (MV3 requires this to live outside the service worker)
│   ├── content.js        # Reads video metadata, samples video frames
│   └── sidepanel.html/js/css # The UI you interact with while watching
└── web/                # Production web frontend (Render Static Site + Proxy Rewrites)
    ├── index.html          # Landing page with dynamic pricing pass links
    ├── login.html          # Login portal supporting URL redirects
    ├── dashboard.html      # User library and active plan subscription view
    ├── payments.html       # M-Pesa checkout terminal with real-time STK polling
    ├── api.js              # Core fetch wrapper with automatic token refresh & CSRF handling
    ├── password-utils.js   # UI utility scripts
    └── styles.css          # Global design system