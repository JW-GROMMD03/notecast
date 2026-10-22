"""
Unified AI provider layer.
Includes strict client timeouts, latency tracking, diagnostic error logging, 
and audio transcription routing with fail-fast provider rotation.
"""
import base64
import io
import json
import logging
import os
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
    if not isinstance(raw_text, str):
        return {}
    
    text = raw_text.strip()
    match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
    if match:
        text = match.group(1).strip()
        
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError as e:
        log.warning(f"JSON decode failed, attempting recovery: {e}")
        try:
            sanitized = re.sub(r'[\x00-\x1f\x7f-\x9f]', lambda m: '\\u%04x' % ord(m.group(0)), text)
            return json.loads(sanitized, strict=False)
        except Exception:
            pass

        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                sub = text[start:end+1]
                sanitized_sub = re.sub(r'[\x00-\x1f\x7f-\x9f]', lambda m: '\\u%04x' % ord(m.group(0)), sub)
                return json.loads(sanitized_sub, strict=False)
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

    def chat_json(self, system: str, user: str, max_tokens: int = 2500) -> dict:
        if not self.configured:
            raise RuntimeError("Gemini is not configured.")
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

    def chat_text(self, system: str, user: str, max_tokens: int = 2500) -> dict:
        if not self.configured:
            raise RuntimeError("Gemini is not configured.")
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

    def embed(self, texts: list[str]) -> dict:
        if not self.configured:
            raise RuntimeError("Gemini is not configured.")
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
        self.api_key = settings.GROQ_API_KEY or os.getenv("GROQ_API_KEY", "")
        self.configured = bool(self.api_key)
        self._client = OpenAI(
            api_key=self.api_key, 
            base_url="https://api.groq.com/openai/v1", 
            timeout=85.0, 
            max_retries=1
        ) if self.configured else None

    def chat_json(self, system: str, user: str, max_tokens: int = 2500) -> dict:
        if not self.configured:
            raise RuntimeError("Groq is not configured.")
        start = time.time()
        if "json" not in system.lower():
            system += "\nImportant: You must respond exclusively in valid JSON format."
            
        resp = self._client.chat.completions.create(
            model=settings.GROQ_TEXT_MODEL,
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

    def chat_text(self, system: str, user: str, max_tokens: int = 2500) -> dict:
        if not self.configured:
            raise RuntimeError("Groq is not configured.")
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

    def transcribe(self, audio_bytes: bytes, filename: str, vocabulary_hint: str = "") -> dict:
        if not self.configured:
            raise RuntimeError("Groq is not configured.")
        start = time.time()
        file_tuple = (filename, audio_bytes, "audio/webm")
        prompt = vocabulary_hint if vocabulary_hint else "Technical video lecture with complex diagrams and terminology."
        
        resp = self._client.audio.transcriptions.create(
            file=file_tuple,
            model=settings.GROQ_ASR_MODEL or "whisper-large-v3",
            prompt=prompt,
            response_format="json",
            temperature=0.0
        )
        
        return {
            "text": getattr(resp, "text", ""),
            "confidence": 0.95,
            "provider": self.name,
            "model": settings.GROQ_ASR_MODEL or "whisper-large-v3",
            "latency_ms": int((time.time() - start) * 1000),
        }


# ---------------------------------------------------------------------------
# OpenRouter
# ---------------------------------------------------------------------------

class OpenRouterProvider:
    name = "openrouter"

    def __init__(self):
        key = getattr(settings, "OPENROUTER_API_KEY", None) or os.getenv("OPENROUTER_API_KEY", "")
        self.configured = bool(key)
        self._client = OpenAI(
            api_key=key, 
            base_url="https://openrouter.ai/api/v1", 
            timeout=85.0,
            max_retries=1
        ) if self.configured else None
        self.model = getattr(settings, "OPENROUTER_TEXT_MODEL", "meta-llama/llama-3.3-70b-instruct:free")

    def chat_json(self, system: str, user: str, max_tokens: int = 2500) -> dict:
        if not self.configured:
            raise RuntimeError("OpenRouter is not configured.")
        start = time.time()
        if "json" not in system.lower():
            system += "\nImportant: You must respond exclusively in valid JSON format."
            
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
            extra_headers={"HTTP-Referer": "https://notecast.app", "X-Title": "NoteCast AI"}
        )
        content = resp.choices[0].message.content
        parsed_data = safe_parse_json(content)
        return {
            "data": parsed_data,
            "provider": self.name,
            "model": self.model,
            "latency_ms": int((time.time() - start) * 1000),
            "tokens": getattr(resp.usage, "total_tokens", 0),
        }

    def chat_text(self, system: str, user: str, max_tokens: int = 2500) -> dict:
        if not self.configured:
            raise RuntimeError("OpenRouter is not configured.")
        start = time.time()
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
            extra_headers={"HTTP-Referer": "https://notecast.app", "X-Title": "NoteCast AI"}
        )
        text = resp.choices[0].message.content or ""
        return {
            "text": text,
            "provider": self.name,
            "model": self.model,
            "latency_ms": int((time.time() - start) * 1000),
            "tokens": getattr(resp.usage, "total_tokens", 0),
        }


# ---------------------------------------------------------------------------
# DeepSeek
# ---------------------------------------------------------------------------

class DeepSeekProvider:
    name = "deepseek"

    def __init__(self):
        key = getattr(settings, "DEEPSEEK_API_KEY", None) or os.getenv("DEEPSEEK_API_KEY", "")
        self.configured = bool(key)
        self._client = OpenAI(
            api_key=key, 
            base_url="https://api.deepseek.com", 
            timeout=85.0,
            max_retries=1
        ) if self.configured else None

    def chat_json(self, system: str, user: str, max_tokens: int = 2500) -> dict:
        if not self.configured:
            raise RuntimeError("DeepSeek is not configured.")
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

    def chat_text(self, system: str, user: str, max_tokens: int = 2500) -> dict:
        if not self.configured:
            raise RuntimeError("DeepSeek is not configured.")
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
# Registry + Diagnostic Fallback Runner
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
    errors = {}
    
    # Enforce strict fallback order prioritizing Groq / OpenRouter first to avoid Gemini 429 quota exhaustion
    provider_order = ["groq", "openrouter", "gemini", "deepseek"]
    if order_csv and isinstance(order_csv, str):
        parsed_order = [p.strip().lower() for p in order_csv.split(",") if p.strip()]
        if parsed_order:
            provider_order = parsed_order

    for name in provider_order:
        if name not in _REGISTRY:
            continue
            
        try:
            provider = _get(name)
            if not getattr(provider, "configured", True):
                errors[name] = "Provider not configured"
                continue
        except Exception as init_err:
            errors[name] = f"Init error: {init_err}"
            continue

        tried.append(name)
        method = getattr(provider, method_name, None)
        if method is None:
            errors[name] = f"Method '{method_name}' not implemented"
            continue  

        try:
            log.info(f"Attempting {name}.{method_name}...")
            res = method(*args, **kwargs)
            log.info(f"✅ SUCCESS: {name}.{method_name} completed in {res.get('latency_ms', 0)}ms")
            return res
        except Exception as e:
            errors[name] = str(e)
            log.error(f"❌ FAIL: {name}.{method_name} error: {e}. Immediately failing over...")
            continue

    raise RuntimeError(f"All configured providers failed for {method_name}. Tried: {tried}. Errors: {errors}")