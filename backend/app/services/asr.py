"""
ASR: Direct, straightforward audio transcription bypassing the fallback registry.
"""
import logging
import tempfile
import os
import time
from openai import OpenAI
from ..config import settings

log = logging.getLogger("notecast.asr")

def transcribe_chunk(audio_bytes: bytes, filename: str = "chunk.webm", vocabulary_hint: str = "") -> dict:
    """Detects speech and converts it to text directly using Groq Whisper."""
    
    if not audio_bytes or len(audio_bytes) < 512:
        return {"text": "", "confidence": 0.0, "latency_ms": 0}

    start = time.time()
    try:
        # 1. Safely save and read the audio chunk
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_file:
            tmp_file.write(audio_bytes)
            tmp_path = tmp_file.name

        with open(tmp_path, "rb") as f:
            file_tuple = (filename, f.read(), "audio/webm")

        os.remove(tmp_path)

        # 2. Get API key directly from environment
        api_key = getattr(settings, "GROQ_API_KEY", None) or os.getenv("GROQ_API_KEY", "")
        if not api_key:
            log.error("❌ DIRECT ASR FAILED: GROQ_API_KEY is completely missing from Render environment.")
            return {"text": "", "confidence": 0.0, "latency_ms": 0}

        # 3. Direct API Call bypassing providers.py
        log.info("Attempting direct transcription to Groq API...")
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
            timeout=30.0
        )

        prompt = vocabulary_hint if vocabulary_hint else "Technical video lecture with complex terminology."

        resp = client.audio.transcriptions.create(
            file=file_tuple,
            model="whisper-large-v3",
            prompt=prompt,
            response_format="json",
            temperature=0.0
        )

        text = getattr(resp, "text", "")
        latency = int((time.time() - start) * 1000)
        
        log.info(f"✅ DIRECT ASR SUCCESS! Transcribed {len(text)} characters in {latency}ms.")

        return {
            "text": text,
            "confidence": 0.95,
            "provider": "groq-direct",
            "model": "whisper-large-v3",
            "latency_ms": latency
        }

    except Exception as e:
        # This will now print the EXACT error from the API instead of Tried: []
        log.error(f"❌ DIRECT ASR FAILED: {str(e)}")
        return {"text": "", "confidence": 0.0, "latency_ms": 0}