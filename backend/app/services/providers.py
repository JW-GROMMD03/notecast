"""
Unified AI provider layer.

Four providers, in priority order per capability:

1. Gemini     (Google AI Studio free tier)   — text, vision, audio transcription, embeddings
2. Groq       (free tier)                     — text (Llama), vision (Llama vision), audio (Whisper-large-v3)
3. OpenRouter (free tier / flexible pool)     — text (Llama/Gemma free models)
4. DeepSeek   (near-free pay-as-you-go)      — text only

`call_with_fallback()` tries each configured provider in order for a given
capability and moves to the next on any error (auth failure, rate limit,
timeout, model not found, etc.).
"""
import base64
import io
import json
import logging
import re
import time
from openai import OpenAI

from ..config import settings

log = logging.getLogger("notecast.providers")

try:
    import google.generativeai as genai
except ImportError:  
    genai = None


def safe_parse_json(raw_text: str) -> dict:
    """
    Safely cleans markdown code blocks and handles malformed AI JSON strings 
    without throwing a crash exception.
    """
    if not isinstance(raw_text, str):
        return {}
    
    text = raw_text.strip()
    match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
    if match:
        text = match.group(1).strip()
        
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        log.warning(f"JSON decode failed, attempting recovery: {e} | Raw content: {text[:100]}...")
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end+1])
            except Exception:
                pass
        return {"heading": "Note Section", "body_md": text}


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

class GeminiProvider:
    name = "gemini"

    def __init__(self):
        self.configured = bool(settings.GEMINI_API_KEY) and genai is not None
        if self.configured:
            genai.configure(api_key=settings.GEMINI_API_KEY)

    def chat_json(self, system: str, user: str, max_tokens: int = 1500) -> dict:
        model = genai.GenerativeModel(settings.GEMINI_TEXT_MODEL, system_instruction=system)
        start = time.time()
        resp = model.generate_content(
            user,
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json", max_output_tokens=max_tokens
            ),
        )
        parsed_data = safe_parse_json(resp.text)
        return {
            "data": parsed_data,
            "provider": self.name,
            "model": settings.GEMINI_TEXT_MODEL,
            "latency_ms": int((time.time() - start) * 1000),
            "tokens": getattr(resp.usage_metadata, "total_token_count", 0) if resp.usage_metadata else 0,
        }

    def chat_text(self, system: str, user: str, max_tokens: int = 2048) -> dict:
        model = genai.GenerativeModel(settings.GEMINI_TEXT_MODEL, system_instruction=system)
        start = time.time()
        resp = model.generate_content(
            user,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=max_tokens
            ),
        )
        text = (resp.text or "").strip()
        return {
            "text": text,
            "provider": self.name,
            "model": settings.GEMINI_TEXT_MODEL,
            "latency_ms": int((time.time() - start) * 1000),
            "tokens": getattr(resp.usage_metadata, "total_token_count", 0) if resp.usage_metadata else 0,
        }

    def vision_json(self, system: str, user_text: str, image_bytes: bytes, mime: str = "image/webp", max_tokens: int = 400) -> dict:
        model = genai.GenerativeModel(settings.GEMINI_VISION_MODEL, system_instruction=system)
        start = time.time()
        resp = model.generate_content(
            [user_text, {"mime_type": mime, "data": image_bytes}],
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json", max_output_tokens=max_tokens
            ),
        )
        parsed_data = safe_parse_json(resp.text)
        return {
            "data": parsed_data,
            "provider": self.name,
            "model": settings.GEMINI_VISION_MODEL,
            "latency_ms": int((time.time() - start) * 1000),
            "tokens": getattr(resp.usage_metadata, "total_token_count", 0) if resp.usage_metadata else 0,
        }

    def transcribe(self, audio_bytes: bytes, filename: str, vocabulary_hint: str = "") -> dict:
        mime = "audio/webm"
        model = genai.GenerativeModel(settings.GEMINI_ASR_MODEL)
        prompt = "Transcribe this audio verbatim. Respond with the transcript text only, nothing else."
        if vocabulary_hint:
            prompt += f" Likely domain terms you may hear: {vocabulary_hint}"
        start = time.time()
        resp = model.generate_content([prompt, {"mime_type": mime, "data": audio_bytes}])
        text = (resp.text or "").strip()
        return {
            "text": text,
            "confidence": 0.85 if text else 0.0,
            "provider": self.name,
            "model": settings.GEMINI_ASR_MODEL,
            "latency_ms": int((time.time() - start) * 1000),
        }

    def embed(self, texts: list[str]) -> dict:
        start = time.time()
        vectors = [genai.embed_content(model=f"models/{settings.GEMINI_EMBED_MODEL}", content=t)["embedding"] for t in texts]
        return {
            "embeddings": vectors,
            "provider": self.name,
            "model": settings.GEMINI_EMBED_MODEL,
            "latency_ms": int((time.time() - start) * 1000),
        }


# ---------------------------------------------------------------------------
# Groq
# ---------------------------------------------------------------------------

class GroqProvider:
    name = "groq"

    def __init__(self):
        self.configured = bool(settings.GROQ_API_KEY)
        self._client = OpenAI(api_key=settings.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1", max_retries=0) if self.configured else None

    def chat_json(self, system: str, user: str, max_tokens: int = 1500) -> dict:
        start = time.time()
        if "json" not in system.lower():
            system += "\nImportant: You must respond exclusively in valid JSON format."
            
        resp = self._client.chat.completions.create(
            model=settings.GROQ_TEXT_MODEL,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
        )
        content = resp.choices[0].message.content
        parsed_data = safe_parse_json(content)
        return {
            "data": parsed_data,
            "provider": self.name,
            "model": settings.GROQ_TEXT_MODEL,
            "latency_ms": int((time.time() - start) * 1000),
            "tokens": getattr(resp.usage, "total_tokens", 0),
        }

    def chat_text(self, system: str, user: str, max_tokens: int = 2048) -> dict:
        start = time.time()
        resp = self._client.chat.completions.create(
            model=settings.GROQ_TEXT_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
        )
        text = resp.choices[0].message.content or ""
        return {
            "text": text,
            "provider": self.name,
            "model": settings.GROQ_TEXT_MODEL,
            "latency_ms": int((time.time() - start) * 1000),
            "tokens": getattr(resp.usage, "total_tokens", 0),
        }

    def vision_json(self, system: str, user_text: str, image_bytes: bytes, mime: str = "image/webp", max_tokens: int = 400) -> dict:
        b64 = base64.b64encode(image_bytes).decode()
        start = time.time()
        resp = self._client.chat.completions.create(
            model=settings.GROQ_VISION_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    ],
                },
            ],
            max_tokens=max_tokens,
        )
        content = resp.choices[0].message.content
        parsed_data = safe_parse_json(content)
        return {
            "data": parsed_data,
            "provider": self.name,
            "model": settings.GROQ_VISION_MODEL,
            "latency_ms": int((time.time() - start) * 1000),
            "tokens": getattr(resp.usage, "total_tokens", 0),
        }

    def transcribe(self, audio_bytes: bytes, filename: str, vocabulary_hint: str = "") -> dict:
        start = time.time()
        buf = io.BytesIO(audio_bytes)
        buf.name = filename
        resp = self._client.audio.transcriptions.create(
            model=settings.GROQ_ASR_MODEL,
            file=buf,
            prompt=vocabulary_hint[:800] if vocabulary_hint else None,
            response_format="verbose_json",
        )
        text = (resp.text or "").strip()
        segments = getattr(resp, "segments", None) or []
        if segments:
            avg_logprob = sum((s.get("avg_logprob", -0.2) if isinstance(s, dict) else getattr(s, "avg_logprob", -0.2)) for s in segments) / len(segments)
            confidence = max(0.0, min(1.0, 1.0 + avg_logprob))
        else:
            confidence = 0.9 if text else 0.0
        return {
            "text": text,
            "confidence": confidence,
            "provider": self.name,
            "model": settings.GROQ_ASR_MODEL,
            "latency_ms": int((time.time() - start) * 1000),
        }


# ---------------------------------------------------------------------------
# OpenRouter (New Free Failover Provider)
# ---------------------------------------------------------------------------

class OpenRouterProvider:
    name = "openrouter"

    def __init__(self):
        key = getattr(settings, "OPENROUTER_API_KEY", None)
        self.configured = bool(key)
        self._client = OpenAI(
            api_key=key, 
            base_url="https://openrouter.ai/api/v1", 
            max_retries=0
        ) if self.configured else None

    def chat_json(self, system: str, user: str, max_tokens: int = 1500) -> dict:
        start = time.time()
        if "json" not in system.lower():
            system += "\nImportant: You must respond exclusively in valid JSON format."
            
        resp = self._client.chat.completions.create(
            model="meta-llama/llama-3.3-70b-instruct:free",
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
            extra_headers={
                "HTTP-Referer": "https://notecast.app",
                "X-Title": "NoteCast AI"
            }
        )
        content = resp.choices[0].message.content
        parsed_data = safe_parse_json(content)
        return {
            "data": parsed_data,
            "provider": self.name,
            "model": "meta-llama/llama-3.3-70b-instruct:free",
            "latency_ms": int((time.time() - start) * 1000),
            "tokens": getattr(resp.usage, "total_tokens", 0),
        }

    def chat_text(self, system: str, user: str, max_tokens: int = 2048) -> dict:
        start = time.time()
        resp = self._client.chat.completions.create(
            model="meta-llama/llama-3.3-70b-instruct:free",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
            extra_headers={
                "HTTP-Referer": "https://notecast.app",
                "X-Title": "NoteCast AI"
            }
        )
        text = resp.choices[0].message.content or ""
        return {
            "text": text,
            "provider": self.name,
            "model": "meta-llama/llama-3.3-70b-instruct:free",
            "latency_ms": int((time.time() - start) * 1000),
            "tokens": getattr(resp.usage, "total_tokens", 0),
        }


# ---------------------------------------------------------------------------
# DeepSeek
# ---------------------------------------------------------------------------

class DeepSeekProvider:
    name = "deepseek"

    def __init__(self):
        self.configured = bool(settings.DEEPSEEK_API_KEY)
        self._client = OpenAI(api_key=settings.DEEPSEEK_API_KEY, base_url="https://api.deepseek.com", max_retries=0) if self.configured else None

    def chat_json(self, system: str, user: str, max_tokens: int = 1500) -> dict:
        start = time.time()
        resp = self._client.chat.completions.create(
            model=settings.DEEPSEEK_TEXT_MODEL,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
        )
        content = resp.choices[0].message.content
        parsed_data = safe_parse_json(content)
        return {
            "data": parsed_data,
            "provider": self.name,
            "model": settings.DEEPSEEK_TEXT_MODEL,
            "latency_ms": int((time.time() - start) * 1000),
            "tokens": getattr(resp.usage, "total_tokens", 0),
        }

    def chat_text(self, system: str, user: str, max_tokens: int = 2048) -> dict:
        start = time.time()
        resp = self._client.chat.completions.create(
            model=settings.DEEPSEEK_TEXT_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
        )
        text = resp.choices[0].message.content or ""
        return {
            "text": text,
            "provider": self.name,
            "model": settings.DEEPSEEK_TEXT_MODEL,
            "latency_ms": int((time.time() - start) * 1000),
            "tokens": getattr(resp.usage, "total_tokens", 0),
        }


# ---------------------------------------------------------------------------
# Registry + fallback runner
# ---------------------------------------------------------------------------

_REGISTRY = {
    "gemini": GeminiProvider,
    "groq": GroqProvider,
    "openrouter": OpenRouterProvider,
    "deepseek": DeepSeekProvider,
}
_instances: dict[str, object] = {}


def _get(name: str):
    if name not in _instances:
        _instances[name] = _REGISTRY[name]()
    return _instances[name]


def call_with_fallback(order_csv: str, method_name: str, *args, **kwargs) -> dict:
    tried = []
    for name in settings.order(order_csv):
        if name not in _REGISTRY:
            log.warning("unknown provider %r in order list, skipping", name)
            continue
        provider = _get(name)
        if not getattr(provider, "configured", False):
            continue  
        method = getattr(provider, method_name, None)
        if method is None:
            continue  
        tried.append(name)
        try:
            return method(*args, **kwargs)
        except Exception as e:  
            log.warning("%s.%s failed (%s), falling over to next provider", name, method_name, e)
            continue

    if not tried:
        raise RuntimeError(
            f"No provider is configured for this capability. Set an API key for at least one of: "
            f"{', '.join(settings.order(order_csv))} (see .env.example)."
        )
    raise RuntimeError(f"All configured providers failed for {method_name}: tried {tried}")


async def llm_chat_completion(capability: str, messages: list, temperature: float = 0.7) -> dict:
    """
    Compatibility wrapper matching routers.diagrams expectations.
    Routes through call_with_fallback using gemini, groq, openrouter, deepseek.
    """
    system = ""
    user = ""
    for m in messages:
        if m.get("role") == "system":
            system = m.get("content", "")
        elif m.get("role") == "user":
            user = m.get("content", "")

    fallback_order = "gemini,groq,openrouter,deepseek"

    try:
        res = call_with_fallback(fallback_order, "chat_json", system, user)
        return {"content": res.get("data", {})}
    except Exception as e:
        log.warning(f"chat_json fallback failed in llm_chat_completion, trying chat_text: {e}")
        res = call_with_fallback(fallback_order, "chat_text", system, user)
        return {"content": res.get("text", "")}