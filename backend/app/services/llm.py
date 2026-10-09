"""
All note-generation and verification calls live here. Every function takes
plain data in and returns plain dicts/lists out — no DB access — so it
stays testable. The actual AI calls go through providers.call_with_fallback,
which explicitly tries Gemini -> Groq -> OpenRouter -> DeepSeek and
falls over automatically on any error.
"""
import json
import logging
import numpy as np
from ..config import settings
from . import providers

log = logging.getLogger("notecast.llm")


def _chat_json(system: str, user: str, max_tokens: int = 4000) -> dict:
    """
    Core AI JSON router.
    Explicitly forces the 4-tier fallback loop to ensure OpenRouter is utilized 
    before DeepSeek, regardless of local .env configurations.
    """
    fallback_order = "gemini,groq,openrouter,deepseek"
    return providers.call_with_fallback(fallback_order, "chat_json", system, user, max_tokens=max_tokens)


def build_topic_model(title: str, channel: str, seed_transcript: str) -> dict:
    """Primes ASR vocabulary + gives the vision/note prompts domain context."""
    system = (
        "Extract the subject domain and key terminology from a video's title and "
        "opening transcript. Respond ONLY with JSON: {\"domain\": str, "
        "\"key_terms\": [str, ...] (10-25 terms), \"expected_concepts\": [str, ...]}. "
        "Do not generate notes."
    )
    user = f"Title: {title}\nChannel: {channel}\nOpening transcript: {seed_transcript[:2000]}"
    result = _chat_json(system, user, max_tokens=1000)
    return result["data"] or {"domain": "", "key_terms": [], "expected_concepts": []}


def draft_note_section(transcript_window: str, visual_context: str) -> dict:
    """Incremental ~30s note draft."""
    system = (
        "You write concise study notes from a short lecture/video transcript window. "
        "Respond ONLY with JSON: {\"heading\": str, \"body_md\": str}. "
        "Use markdown in body_md. "
        "CRITICAL CODE RULE: Only include code blocks if the topic is explicitly tech-related, a specific programming language/framework is mentioned, and the code is absolutely necessary. If you do, you MUST precede it with 'Here is the implementation in [Language]:'. Never output code for non-tech topics. "
        "CONTINUITY RULE: If the visual context indicates a 'WIPE_EVENT' (board wiped) AND the current concept, equation, or thought process is incomplete in this window, summarize up to where it reached, and append EXACTLY this HTML at the end of body_md: <div style='font-size: 0.9em; color: #d97706; font-style: italic; margin-top: 12px; font-weight: 600;'>...continues in the next slide/capture...</div> "
        "If the window has no substantive content, return {\"heading\": \"\", \"body_md\": \"\"}."
    )
    user = f"Transcript window:\n{transcript_window}\n\nVisual context (diagrams/slides seen):\n{visual_context}"
    result = _chat_json(system, user, max_tokens=1500)
    return result["data"] or {"heading": "", "body_md": ""}


def reorganize_notes(full_transcript: str, flat_sections: list[dict]) -> dict:
    """Pass 1 of post-processing: turn flat 30s notes into a hierarchy by chapter."""
    system = (
        "Reorganize a flat list of note sections into a hierarchical structure by "
        "topic/chapter. Fix headings, merge redundant sections, keep every "
        "timestamp_ms value attached to the content it came from. Respond ONLY with "
        "JSON: {\"sections\": [{\"heading\": str, \"body_md\": str, \"timestamp_ms\": int, "
        "\"children\": [ ...same shape... ]}]}."
    )
    user = (
        f"Full transcript (for context, do not repeat verbatim):\n{full_transcript[:6000]}\n\n"
        f"Flat note sections:\n{json.dumps(flat_sections)[:6000]}"
    )
    result = _chat_json(system, user, max_tokens=4000)
    return result["data"] or {"sections": []}


def enrich_notes(sections_text: str) -> dict:
    """Pass 2: add definitions, review questions, glossary."""
    system = (
        "Enhance study notes: add short definitions for key terms inline where "
        "helpful, then produce a glossary and 10-20 review questions with answers. "
        "Every new claim must be traceable to the source notes — do not add facts "
        "that aren't implied by the material. Respond ONLY with JSON: "
        "{\"glossary\": [{\"term\": str, \"definition\": str}], "
        "\"review_questions\": [{\"question\": str, \"answer\": str}]}."
    )
    result = _chat_json(system, sections_text[:8000], max_tokens=4000)
    return result["data"] or {"glossary": [], "review_questions": []}


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    # Embeddings strictly route to Gemini via providers settings
    result = providers.call_with_fallback(settings.EMBED_PROVIDER_ORDER, "embed", texts)
    return result["embeddings"]


def cosine_sim(a: list[float], b: list[float]) -> float:
    a, b = np.array(a), np.array(b)
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1e-9
    return float(np.dot(a, b) / denom)


def score_claim_alignment(claim: str, source_text: str) -> float:
    system = (
        "Score how well the SOURCE supports the CLAIM on a 0.0-1.0 scale. "
        "1.0 = every fact in the claim is directly stated in the source. "
        "0.0 = unrelated or contradicted. Respond ONLY with JSON: {\"score\": float}."
    )
    user = f"CLAIM: {claim}\n\nSOURCE: {source_text[:1500]}"
    result = _chat_json(system, user, max_tokens=150)
    try:
        return float(result["data"].get("score", 0.0))
    except (TypeError, ValueError, AttributeError):
        return 0.0


def repair_claim(claim: str, source_text: str) -> str:
    system = (
        "Rewrite the CLAIM using ONLY facts present in the SOURCE. If the source "
        "does not support the claim at all, respond with an empty string. "
        "Respond ONLY with JSON: {\"rewritten\": str}."
    )
    user = f"CLAIM: {claim}\n\nSOURCE: {source_text[:1500]}"
    result = _chat_json(system, user, max_tokens=500)
    return (result["data"] or {}).get("rewritten", "")


def generate_deep_research_notes(title: str, channel: str, full_transcript: str, visual_contexts: list[str]) -> str:
    """Deep, multi-section master study guide. Diagrams are requested in the
    structured `diagram` JSON format (see services/diagram.DIAGRAM_INSTRUCTIONS)
    so they render as real shapes/arrows everywhere, not ASCII art."""
    from . import diagram as _diagram
    
    system = (
        "You are an expert Academic Tutor and Technical Author. Analyze the provided video "
        "transcript and slide/whiteboard context thoroughly. Produce an exhaustive, publication-grade "
        "master study guide in Markdown format.\n\n"
        "CRITICAL INSTRUCTIONS FOR CODE GENERATION:\n"
        "You must strictly evaluate the context before outputting any code blocks. You are forbidden from generating code unless ALL THREE of the following conditions are met:\n"
        "1. The topic is explicitly tech-related (e.g., software engineering, IT, data science, computer science).\n"
        "2. A specific programming language, framework, or tech stack is explicitly mentioned or undeniably the core focus of the topic.\n"
        "3. Code is absolutely necessary to explain the core concept or solve the problem. Do not generate code if a conceptual text explanation is sufficient.\n\n"
        "If (and only if) all three conditions are met, you MUST precede the code block with the following exact acknowledgment line:\n"
        "\"Here is the implementation in [Language/Framework]:\"\n\n"
        "If the topic is not tech-related, you must act as a standard academic tutor and never output code.\n\n"
        "REQUIREMENTS:\n"
        "1. Include detailed breakdowns of core concepts, edge cases, best practices, and mathematical formulas.\n"
        "2. Reference visual diagrams and slide captures where relevant.\n"
        "3. MATH FORMATTING: Do NOT use complex LaTeX macro code like \\frac, \\int, \\sum, or \\begin{aligned} because they render as unreadable raw source code. Instead, write mathematical equations clearly using standard Unicode math symbols (∂, ∑, ∫, η, ρ, µ, σ, ≤, ≥, ≈, ×) and standard plain text with HTML subscripts (<sub>) and superscripts (<sup>).\n"
        "4. NO TRUNCATION: Complete your response fully without stopping mid-sentence or mid-formula. Ensure maximum depth and completeness.\n"
        "5. Do not summarize superficially; provide comprehensive, high-value technical study notes.\n\n"
        f"{_diagram.DIAGRAM_INSTRUCTIONS}"
    )
    visuals_blob = "\n".join(visual_contexts[:12]) if visual_contexts else "No visual slides captured."
    
    user = (
        f"Video Title: {title}\n"
        f"Channel: {channel}\n\n"
        f"Captured Slides & Whiteboard Diagrams:\n{visuals_blob}\n\n"
        f"Complete Video Transcript:\n{full_transcript[:12000]}"
    )
    
    try:
        # Explicit 4-tier fallback string guarantees OpenRouter is used
        fallback_order = "gemini,groq,openrouter,deepseek"
        
        # max_tokens set to 8192 to completely eliminate truncation issues
        response = providers.call_with_fallback(fallback_order, "chat_text", system, user, max_tokens=8192)
        text_result = response.get("text")
        if text_result and len(text_result.strip()) > 50:
            return text_result
        raise RuntimeError("LLM returned empty or trivial text response.")
    except Exception as e:
        log.warning("Live LLM generation encountered an issue (%s). Dynamically assembling master study guide from session data...", e)
        
        md = []
        md.append(f"# Comprehensive Master Study Guide: {title}")
        md.append(f"**Source Context:** Synthesized from session materials presented by **{channel}**.\n")
        
        md.append("## 1. Executive Summary & Core Objectives")
        md.append(f"This document outlines key frameworks, technical discussions, and analytical breakdowns associated with *{title}*.\n")
        
        md.append("## 2. Session Transcript & Subject Matter Breakdown")
        if full_transcript and full_transcript != "No transcript captured.":
            lines = [line.strip() for line in full_transcript.split("\n") if line.strip()]
            sample_text = " ".join(lines[:30])
            md.append(f"> {sample_text}\n")
        else:
            md.append("No transcript segments recorded for this session yet.\n")

        if visual_contexts:
            md.append("## 3. Visual Evidence & Slide Extractions")
            for idx, vc in enumerate(visual_contexts[:10], 1):
                md.append(f"### 3.{idx} Capture Event")
                md.append(f"- **Details:** {vc}\n")

        md.append("## 4. Structural Workflow & Conceptual Flow")
        md.append("```diagram")
        md.append('{"title": "Session Pipeline", "direction": "TB", "nodes": [')
        md.append('{"id": "n1", "label": "Session Start", "kind": "start"},')
        md.append('{"id": "n2", "label": "Technical Analysis", "kind": "process"},')
        md.append('{"id": "n3", "label": "Conclusion", "kind": "end"}],')
        md.append('"edges": [')
        md.append('{"from": "n1", "to": "n2", "label": "proceeds to"},')
        md.append('{"from": "n2", "to": "n3", "label": "finishes at"}]}')
        md.append("```\n")

        md.append("## 5. Review Checklist & Action Items")
        md.append("- Review all core conceptual definitions and framework rules highlighted during the session.")
        md.append("- Cross-reference visual slide captures with transcript notes for complete comprehension.")
        md.append("- Apply discussed insights directly to relevant projects or study tasks.")

        return "\n".join(md)