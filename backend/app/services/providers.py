"""
Unified AI provider layer.
Includes strict client timeouts, latency tracking, diagnostic error logging, 
and audio transcription routing.
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
        # Fallback directly to os.getenv incase settings hasn't loaded properly
        self.api_key = settings.GROQ_API_KEY or os.getenv("GROQ_API_KEY", "")
        self.configured = bool(self.api_key)
        log.info(f"GroqProvider initialized. Configured: {self.configured}, Key length: {len(self.api_key)}")
        self._client = OpenAI(
            api_key=self.api_key, 
            base_url="https://api.groq.com/openai/v1", 
            timeout=85.0, 
            max_retries=1
        ) if self.configured else None

    def chat_json(self, system: str, user: str, max_tokens: int = 2500) -> dict:
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
        """Transcribes audio using Groq's fast Whisper API."""
        start = time.time()
        if not self._client:
            raise RuntimeError("Groq client is not initialized ( missing API key )")
            
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
            "model": settings.DEEPSEERT_TEXT_MODEL if hasattr(settings, "DEEPSEEK_TEXT_MODEL") else "deepseek-chat",
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
    """
    Forced diagnostic fallback runner. Guarantees that providers in the order 
    are attempted and logs exact failure reasons instead of returning Tried: [].
    """
    tried = []
    errors = {}
    
    if not order_csv or not isinstance(order_csv, str):
        provider_order = ["groq", "gemini"]
    else:
        provider_order = [p.strip().lower() for p in order_csv.split(",") if p.strip()]
        if not provider_order:
            provider_order = ["groq", "gemini"]
    
    provider_overrides = kwargs.pop("provider_overrides", None)
    if provider_overrides is None and len(args) >= 3 and isinstance(args[2], dict):
        provider_overrides = args[2]
        args_list = list(args)
        args_list.pop(2)
        args = tuple(args_list)

    for name in provider_order:
        if name not in _REGISTRY:
            log.warning(f"Provider '{name}' not found in registry.")
            continue
            
        provider = _get(name)
        
        # Force attempt even if configured is False, to expose the exact config/key error in logs
        tried.append(name)
        
        method = getattr(provider, method_name, None)
        if method is None:
            errors[name] = f"Method '{method_name}' not implemented on provider '{name}'"
            log.warning(f"❌ FAIL: {name} lacks method {method_name}")
            continue  
            
        current_args = list(args)
        current_kwargs = kwargs.copy()

        if provider_overrides and name in provider_overrides:
            if len(current_args) > 0 and isinstance(current_args[0], str):
                current_args[0] = provider_overrides[name]
            elif "system" in current_kwargs:
                current_kwargs["system"] = provider_overrides[name]

        try:
            log.info(f"Attempting {name}.{method_name}...")
            res = method(*current_args, **current_kwargs)
            log.info(f"✅ SUCCESS: {name}.{method_name} completed in {res.get('latency_ms', 0)}ms")
            return res
        except Exception as e:
            errors[name] = str(e)
            log.error(f"❌ FAIL: {name}.{method_name} encountered error: {e}", exc_info=True)
            continue

    raise RuntimeError(f"All configured providers failed for {method_name}. Tried: {tried}. Errors: {errors}")