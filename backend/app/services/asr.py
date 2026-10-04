"""
ASR: buffered ~5s audio windows transcribed through the fallback chain
(Groq's free Whisper-large-v3 first, Gemini's audio understanding second
— see settings.ASR_PROVIDER_ORDER). Neither is true sub-second streaming
ASR; this is "near-live" captions rather than word-by-word streaming.
"""
from ..config import settings
from . import providers


def transcribe_chunk(audio_bytes: bytes, filename: str = "chunk.webm", vocabulary_hint: str = "") -> dict:
    """Returns {text, confidence, latency_ms, provider, model}."""
    return providers.call_with_fallback(
        settings.ASR_PROVIDER_ORDER, "transcribe", audio_bytes, filename, vocabulary_hint
    )