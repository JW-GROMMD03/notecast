import json
import logging
import httpx
from ..config import settings

logger = logging.getLogger("notecast.ai_generator")

def _call_deepseek(system_prompt: str, user_prompt: str, response_json: bool = False, timeout: float = 60.0) -> str | dict:
    """Invokes DeepSeek API with standard OpenAI-compatible payload."""
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {getattr(settings, 'DEEPSEEK_API_KEY', '')}", 
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.3
    }
    if response_json:
        payload["response_format"] = {"type": "json_object"}

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content) if response_json else content


def generate_deep_research_notes(title: str, channel: str, full_transcript: str, visual_contexts: list[str]) -> str:
    """Generates structured, publication-grade study notes using DeepSeek with OpenAI fallback."""
    system_prompt = """
    You are NoteCast AI, an elite academic researcher and pedagogical engineer.
    Your task is to transform session transcripts and visual OCR context into an exhaustive Master Study Guide.

    CRITICAL FORMATTING & CONTENT RULES:
    1. EXHAUSTIVE CONCEPTUAL DEPTH: Break down every theoretical concept, formula, algorithm, and engineering principle in full detail. Never truncate or summarize superficially.
    2. LaTeX MATHEMATICAL FORMULAS: Format all equations using standard LaTeX syntax. Use $$...$$ for standalone display equations and $...$ for inline variables. Include step-by-step mathematical proofs and variable definitions.
    3. JSON DIAGRAM ENCAPSULATION: Always enclose diagram layouts inside standard ```diagram code blocks:
       ```diagram
       {
         "title": "System Architecture / Concept Flow",
         "direction": "TB",
         "nodes": [{"id": "1", "label": "Input Stage"}, {"id": "2", "label": "Processing Stage"}],
         "edges": [{"from": "1", "to": "2"}]
       }
       ```
    4. TIMESTAMP ANCHORS: Attach explicit timestamp references in the format [MM:SS] or [HH:MM:SS] to all key concept headings.
    5. MARKDOWN FORMATTING: Use clean headers (#, ##, ###), bullet points, and code blocks.
    """

    visual_str = "\n".join(visual_contexts) if visual_contexts else "No visual frame OCR recorded."
    user_prompt = f"""
    Title: {title}
    Presenter / Channel: {channel}

    Visual Frame OCR Context:
    {visual_str}

    Session Transcript / Context:
    {full_transcript}
    """

    # Try DeepSeek first for deep reasoning & cost-efficiency, fallback to OpenAI if keys/quota fail
    try:
        if getattr(settings, "DEEPSEEK_API_KEY", None):
            logger.info("Attempting DeepSeek chat completion for deep research notes...")
            return _call_deepseek(system_prompt, user_prompt, response_json=False, timeout=120.0)
    except Exception as e:
        logger.warning(f"DeepSeek generation failed, failing over to OpenAI: {e}")

    # OpenAI Fallback
    try:
        url = "[https://api.openai.com/v1/chat/completions](https://api.openai.com/v1/chat/completions)"
        headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.3
        }

        with httpx.Client(timeout=120.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Deep AI note generation failed across all providers: {e}")
        return f"# Study Notes: {title}\n\n*Generation fallback triggered due to service timeout.* \n\n## Raw Context Overview\n{full_transcript[:3000]}"


def evaluate_socratic_defense(concept: str, user_explanation: str, context_notes: str) -> dict:
    """Evaluates a student's verbal explanation using DeepSeek/OpenAI Socratic evaluation."""
    system_prompt = """
    You are a Socratic tutor evaluating a student's verbal explanation of a topic using the Feynman Technique.
    Analyze the student's response against the core concept and reference study materials.

    EVALUATION GUIDELINES:
    1. Identify whether the student's explanation is accurate, partially correct, or flawed.
    2. DO NOT reveal the complete answer immediately.
    3. Point out specific gaps, vague language, or misconceptions.
    4. Pose a targeted, guiding Socratic follow-up question that helps them discover the correct reasoning themselves.

    Output MUST be a valid JSON object with keys:
    - "status": ("mastered", "partially_correct", or "needs_work")
    - "score": integer between 0 and 100
    - "feedback": direct constructive evaluation
    - "detected_gaps": array of strings specifying missing details
    - "socratic_question": a probing question to ask next
    """

    user_prompt = f"""
    Target Concept: {concept}
    Reference Context: {context_notes}
    Student Verbal Explanation: "{user_explanation}"
    """

    try:
        if getattr(settings, "DEEPSEEK_API_KEY", None):
            return _call_deepseek(system_prompt, user_prompt, response_json=True, timeout=30.0)
    except Exception as e:
        logger.warning(f"DeepSeek socratic evaluation failed, falling back to OpenAI: {e}")

    try:
        url = "[https://api.openai.com/v1/chat/completions](https://api.openai.com/v1/chat/completions)"
        headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.4
        }

        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return json.loads(data["choices"][0]["message"]["content"])
    except Exception as e:
        logger.error(f"Socratic evaluation error: {e}")
        return {
            "status": "partially_correct",
            "score": 70,
            "feedback": "Your explanation was received, but the AI evaluation service experienced a temporary delay.",
            "detected_gaps": ["Service connection latency"],
            "socratic_question": "Can you summarize the core working principle once more?"
        }