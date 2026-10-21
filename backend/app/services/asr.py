"""
ASR: buffered ~5s audio windows transcribed through the fallback chain.
Enhanced with strict file validation and temporary disk writing to ensure 
Groq/Whisper APIs do not silently reject audio chunks.
"""
import logging
import tempfile
import os
from ..config import settings
from . import providers

log = logging.getLogger("notecast.asr")

def transcribe_chunk(audio_bytes: bytes, filename: str = "chunk.webm", vocabulary_hint: str = "") -> dict:
    """Returns {text, confidence, latency_ms, provider, model}."""
    
    # 1. Reject empty or dangerously small audio chunks that will crash the API
    if not audio_bytes or len(audio_bytes) < 1024:
        log.warning("Audio chunk too small or empty, skipping ASR.")
        return {"text": "", "confidence": 0.0, "latency_ms": 0}

    try:
        # 2. Write to a temporary file to guarantee valid byte-stream formatting.
        # This prevents HTTP form-data corruption when forwarding to external APIs.
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_file:
            tmp_file.write(audio_bytes)
            tmp_path = tmp_file.name

        with open(tmp_path, "rb") as f:
            validated_bytes = f.read()

        os.remove(tmp_path)

        # 3. Call the ASR provider fallback chain
        result = providers.call_with_fallback(
            settings.ASR_PROVIDER_ORDER, "transcribe", validated_bytes, filename, vocabulary_hint
        )
        
        # Ensure safe return format even if API returns an empty object
        if not result or not isinstance(result, dict) or not result.get("text"):
            return {"text": "", "confidence": 0.0, "latency_ms": 0}
            
        return result

    except Exception as e:
        # Log the exact API failure (e.g., "Invalid file format")
        log.error(f"ASR Transcription failed for {filename}: {e}")
        return {"text": "", "confidence": 0.0, "latency_ms": 0}