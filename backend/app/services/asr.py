"""
ASR: buffered ~5s audio windows transcribed through the fallback chain.
Enhanced with explicit provider routing to eliminate Tried: [] errors.
"""
import logging
import tempfile
import os
from ..config import settings
from . import providers

log = logging.getLogger("notecast.asr")

def transcribe_chunk(audio_bytes: bytes, filename: str = "chunk.webm", vocabulary_hint: str = "") -> dict:
    """Returns {text, confidence, latency_ms, provider, model}."""
    
    if not audio_bytes or len(audio_bytes) < 512:
        log.warning("Audio chunk too small or empty, skipping ASR.")
        return {"text": "", "confidence": 0.0, "latency_ms": 0}

    try:
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_file:
            tmp_file.write(audio_bytes)
            tmp_path = tmp_file.name

        with open(tmp_path, "rb") as f:
            validated_bytes = f.read()

        os.remove(tmp_path)

        # Explicitly pass order string from settings or default fallback chain
        order = getattr(settings, "ASR_PROVIDER_ORDER", "groq,gemini")

        result = providers.call_with_fallback(
            order, 
            "transcribe", 
            audio_bytes=validated_bytes, 
            filename=filename, 
            vocabulary_hint=vocabulary_hint
        )
        
        if not result or not isinstance(result, dict) or not result.get("text"):
            return {"text": "", "confidence": 0.0, "latency_ms": 0}
            
        return result

    except Exception as e:
        log.error(f"ASR Transcription failed for {filename}: {e}")
        return {"text": "", "confidence": 0.0, "latency_ms": 0}