"""
Vision pipeline: a cheap local gate (skip talking-head frames) followed by
a vision LLM call only for frames worth analysing. The MobileNet ONNX
classifier from the original design needs a trained model file we don't
have; this ships a lightweight heuristic gate instead (frame-difference +
edge-density, computed with numpy/Pillow — no ML model to download) that
you can drop a real ONNX classifier into later behind the same function
signature.
"""
import base64
import io
import json
import time
import re
import numpy as np
from PIL import Image
from openai import OpenAI
from ..config import settings

# Dynamically select the client and model based on available keys
_client = None
_vision_model = None

if getattr(settings, "GROQ_API_KEY", None):
    _client = OpenAI(
        api_key=settings.GROQ_API_KEY,
        base_url="https://api.groq.com/openai/v1"
    )
    _vision_model = getattr(settings, "GROQ_VISION_MODEL", "llama-3.2-11b-vision-preview")
elif getattr(settings, "GEMINI_API_KEY", None):
    _client = OpenAI(
        api_key=settings.GEMINI_API_KEY,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
    )
    _vision_model = getattr(settings, "GEMINI_VISION_MODEL", "gemini-2.0-flash")


_last_frame_gray = {}  # session_id -> np.ndarray, for perceptual-diff gating

# Strictly enforce JSON formatting and character escaping to prevent API 400 crashes
VISION_PROMPT = """
You analyse a single video frame for a note-taking tool.
Respond ONLY with a valid JSON object matching this exact structure:
{
  "is_meaningful": true,
  "type": "diagram|code|slide|chart|whiteboard|other",
  "description": "Brief summary",
  "extracted_text": "Plain text content without unescaped quotes",
  "latex": null
}

CRITICAL RULES:
1. is_meaningful is false for talking-head shots, ads, or frames with no useful information.
2. You MUST escape all double quotes inside strings with a backslash (\\").
3. Do NOT include raw backslashes or literal newline characters inside strings; use spaces or \\n instead.
"""

def clean_vision_json(raw_text: str) -> dict:
    """
    Parses LLM output and aggressively cleans unescaped quotes and newlines
    to prevent json_validate_failed errors.
    """
    try:
        # First attempt: Try standard JSON load
        return json.loads(raw_text)
    except json.JSONDecodeError:
        # Second attempt: Strip markdown formatting and fix newlines
        cleaned = re.sub(r'\\n', ' ', raw_text)
        cleaned = re.sub(r'\\', '', cleaned)
        
        if "```json" in cleaned:
            try:
                cleaned = cleaned.split("```json")[1].split("```")[0]
            except IndexError:
                pass
                
        try:
            return json.loads(cleaned)
        except Exception:
            # Final fallback: Return generic object so the pipeline does not crash
            return {
                "is_meaningful": True,
                "type": "slide",
                "description": "Visual captured (Text extraction formatting failed)",
                "extracted_text": "",
                "latex": None
            }


def should_capture(session_id: str, image_bytes: bytes) -> bool:
    """Cheap local gate: skip frames that barely changed or look like a
    static talking-head shot (low edge density, low variance)."""
    img = Image.open(io.BytesIO(image_bytes)).convert("L").resize((160, 90))
    arr = np.asarray(img, dtype=np.float32)

    prev = _last_frame_gray.get(session_id)
    _last_frame_gray[session_id] = arr
    if prev is not None:
        diff = np.mean(np.abs(arr - prev))
        if diff < 4.0:  # near-identical frame
            return False

    # Edge density as a proxy for "slide/diagram/code" vs "talking head"
    gx = np.abs(np.diff(arr, axis=1))
    gy = np.abs(np.diff(arr, axis=0))
    edge_density = (np.mean(gx) + np.mean(gy)) / 2
    return edge_density > 6.0


def analyze_frame(image_bytes: bytes, transcript_context: str) -> dict:
    """Send a captured frame + recent transcript to the vision LLM.
    Returns is_meaningful, type, description, extracted_text, latex."""
    if not _client or not _vision_model:
        raise RuntimeError("No vision API key found. GROQ_API_KEY or GEMINI_API_KEY must be set in .env")

    b64 = base64.b64encode(image_bytes).decode()
    start = time.time()
    
    try:
        resp = _client.chat.completions.create(
            model=_vision_model,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": VISION_PROMPT,
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Recent transcript context: {transcript_context[:500]}"},
                        {"type": "image_url", "image_url": {"url": f"data:image/webp;base64,{b64}"}},
                    ],
                },
            ],
            max_tokens=400,
        )
        latency_ms = int((time.time() - start) * 1000)
        
        # Parse and sanitize the response
        raw_content = resp.choices[0].message.content
        data = clean_vision_json(raw_content)
        
        data["_latency_ms"] = latency_ms
        data["_tokens"] = getattr(resp.usage, "total_tokens", 0)
        
    except Exception as e:
        # If the API throws a 400 error (e.g. strict validation failed before returning), 
        # log it and return a safe fallback instead of crashing the capture pipeline.
        print(f"Vision API Error: {e}")
        
        # If Groq returns the failed generation inside the exception, attempt to parse it
        try:
            if hasattr(e, "response") and e.response:
                err_body = e.response.json()
                if "failed_generation" in err_body.get("error", {}):
                    failed_raw = err_body["error"]["failed_generation"]
                    data = clean_vision_json(failed_raw)
                    return data
        except Exception:
            pass

        data = {"is_meaningful": False, "type": "other", "description": "", "extracted_text": "", "latex": None}
        
    return data