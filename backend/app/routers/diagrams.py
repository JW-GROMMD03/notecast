import logging
import json
import re
import asyncio
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session as DbSession
from pydantic import BaseModel, Field
from .. import models, schemas, auth
from ..database import get_db
from ..services import providers

router = APIRouter(prefix="/diagrams", tags=["diagrams"])
logger = logging.getLogger("notecast_diagrams")

class GenerateSimIn(BaseModel):
    topic: str = Field(..., description="The subject to generate a visual simulation for")

@router.post("/generate-sim/")
async def generate_simulation_schema(
    body: GenerateSimIn,
    user: models.User = Depends(auth.get_current_user)
):
    """
    Generates a minimalist, geometric simulation to heavily reduce API tokens,
    with an extended 90-second timeout to accommodate slow model fallback chains.
    """
    safe_topic = body.topic.title().replace('"', '').replace("'", "")
    
    # Ultra-minimal fallback payload utilizing basic geometric shapes
    fallback_payload = {
        "title": f"{safe_topic} — Minimal Visualizer",
        "description": f"Geometric state representation for {safe_topic}.",
        "detailed_lecture": f"<strong>System Mechanics: {safe_topic}</strong><br><br>This system operates through simple sequential state changes. Trigger the execution step below to observe flow logic.",
        "html_code": f"""<!DOCTYPE html>
<html lang='en'>
<head>
<meta charset='utf-8'>
<style>
  body {{ margin: 0; background: #030712; color: #fff; font-family: sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; overflow: hidden; }}
  .sim-container {{ border: 2px solid #1e293b; border-radius: 8px; padding: 40px; display: flex; gap: 20px; align-items: center; background: #0f172a; }}
  .circle {{ width: 60px; height: 60px; background: #3b82f6; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; transition: transform 0.3s, background 0.3s; }}
  .rectangle {{ width: 100px; height: 60px; background: #10b981; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-weight: bold; transition: opacity 0.3s; }}
  .line {{ width: 50px; height: 4px; background: #475569; }}
  button {{ margin-top: 30px; background: #3b82f6; color: white; border: none; padding: 12px 24px; border-radius: 6px; cursor: pointer; }}
</style>
</head>
<body>
  <div class='sim-container'>
    <div class='circle' id='nodeA'>A</div>
    <div class='line'></div>
    <div class='rectangle' id='nodeB'>State</div>
  </div>
  <button onclick='triggerStep()'>Advance Step</button>
  <script>
    let active = false;
    function triggerStep() {{
      active = !active;
      document.getElementById('nodeA').style.transform = active ? 'scale(1.2)' : 'scale(1)';
      document.getElementById('nodeB').style.background = active ? '#eab308' : '#10b981';
      window.parent.postMessage({{ type: 'UPDATE_METRIC', title: 'State', value: active ? 'Running' : 'Idle' }}, '*');
    }}
  </script>
</body>
</html>"""
    }

    # Highly restrictive prompt commanding extreme brevity and basic shapes
    system_prompt = (
        "You are a minimalist computer science educator. Create a highly concise, interactive HTML/JS simulation for the requested topic.\n\n"
        "CRITICAL INSTRUCTIONS TO MINIMIZE TOKENS:\n"
        "1. Write the absolute minimum CSS and JS required.\n"
        "2. Do NOT use external libraries, complex SVGs, or Tailwind.\n"
        "3. You MUST use basic HTML/CSS geometric shapes (rectangles, circles, and lines) to represent all objects and data structures. Use simple divs with border-radius.\n"
        "4. Output MUST be incredibly short and direct.\n\n"
        "Structure your response exactly like this using markdown:\n\n"
        "### TITLE\n"
        "Topic Name\n\n"
        "### DESCRIPTION\n"
        "1-sentence summary.\n\n"
        "### LECTURE\n"
        "Brief explanation.\n\n"
        "### HTML\n"
        "```html\n"
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head>\n"
        "  <style>\n"
        "    body { background: #111; color: #fff; font-family: sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; }\n"
        "    .circle { width: 50px; height: 50px; background: #3b82f6; border-radius: 50%; display: flex; align-items: center; justify-content: center; }\n"
        "    .rectangle { width: 100px; height: 50px; background: #10b981; display: flex; align-items: center; justify-content: center; }\n"
        "    button { margin-top: 20px; padding: 10px; cursor: pointer; }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        "  <!-- Minimal shapes and buttons go here -->\n"
        "  <script>\n"
        "    // Extremely minimal JS logic\n"
        "  </script>\n"
        "</body>\n"
        "</html>\n"
        "```"
    )

    try:
        logger.info(f"Initiating token-optimized minimal simulation for: {body.topic}")
        fallback_order = "gemini,openrouter,deepseek,groq"
        user_prompt = f"Generate a minimal geometric HTML/JS simulation for: {body.topic}"

        # Increased timeout to 90 seconds to allow deep model generation.
        # Max tokens clamped to 2000 to force the AI to respect brevity.
        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None, 
                lambda: providers.call_with_fallback(fallback_order, "chat_text", system_prompt, user_prompt, max_tokens=2000)
            ),
            timeout=90.0
        )
        
        raw_text = result.get("text", "")
        if not raw_text.strip():
            return JSONResponse(content=fallback_payload)

        title_match = re.search(r'###\s*(?:TITLE)\s*\n(.*?)(?=\n###|\Z)', raw_text, re.DOTALL | re.IGNORECASE)
        desc_match = re.search(r'###\s*(?:DESCRIPTION)\s*\n(.*?)(?=\n###|\Z)', raw_text, re.DOTALL | re.IGNORECASE)
        lecture_match = re.search(r'###\s*(?:LECTURE)\s*\n(.*?)(?=\n###|\Z)', raw_text, re.DOTALL | re.IGNORECASE)
        
        html_match = re.search(r'```(?:html)?\s*(.*?)\s*```', raw_text, re.DOTALL | re.IGNORECASE)
        mermaid_match = re.search(r'```(?:mermaid|diagram)?\s*(.*?)\s*```', raw_text, re.DOTALL | re.IGNORECASE)

        extracted_title = title_match.group(1).strip() if title_match else f"{safe_topic} Simulation"
        extracted_desc = desc_match.group(1).strip() if desc_match else f"Minimal interactive model for {safe_topic}."
        extracted_lecture = lecture_match.group(1).strip() if lecture_match else fallback_payload["detailed_lecture"]
        
        if html_match:
            extracted_html = html_match.group(1).strip()
        elif mermaid_match:
            mermaid_code = mermaid_match.group(1).strip()
            extracted_html = f"""<!DOCTYPE html>
<html>
<head>
  <script src='https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js'></script>
  <script>mermaid.initialize({{ startOnLoad: true, theme: 'dark' }});</script>
  <style>
    body {{ margin: 0; background: #030712; color: #fff; font-family: system-ui, sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; }}
    .mermaid {{ background: #0f172a; padding: 25px; border-radius: 12px; border: 1px solid #1e293b; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }}
  </style>
</head>
<body>
  <div class='mermaid'>
    {mermaid_code}
  </div>
  <script>
    window.parent.postMessage({{ type: 'UPDATE_METRIC', title: 'Diagram State', value: 'Rendered' }}, '*');
  </script>
</body>
</html>"""
        else:
            extracted_html = fallback_payload["html_code"]

        return JSONResponse(content={
            "topic": body.topic,
            "title": extracted_title.replace('"', ''),
            "description": extracted_desc.replace('"', ''),
            "detailed_lecture": extracted_lecture,
            "html_code": extracted_html
        })

    except asyncio.TimeoutError:
        logger.warning(f"Simulation generation timed out (>90s). Serving instant fallback.")
        return JSONResponse(content=fallback_payload)
    except Exception as e:
        logger.warning(f"Simulation generation caught exception ({e}). Serving robust canvas.")
        return JSONResponse(content=fallback_payload)

@router.post("/", response_model=schemas.InteractiveDiagramOut, status_code=status.HTTP_201_CREATED)
def create_diagram(body: schemas.InteractiveDiagramCreateIn, db: DbSession = Depends(get_db), user: models.User = Depends(auth.get_current_user)):
    new_diag = models.InteractiveDiagram(user_id=user.id, title=body.title, sim_type=body.sim_type, canvas_state={"nodes": [], "edges": []})
    db.add(new_diag)
    db.commit()
    db.refresh(new_diag)
    return new_diag

@router.get("/", response_model=List[schemas.InteractiveDiagramOut])
def list_diagrams(db: DbSession = Depends(get_db), user: models.User = Depends(auth.get_current_user)):
    return db.query(models.InteractiveDiagram).filter(models.InteractiveDiagram.user_id == user.id).all()

@router.get("/{diagram_id}/", response_model=schemas.InteractiveDiagramOut)
def get_diagram(diagram_id: str, db: DbSession = Depends(get_db), user: models.User = Depends(auth.get_current_user)):
    diag = db.query(models.InteractiveDiagram).filter(models.InteractiveDiagram.id == diagram_id, models.InteractiveDiagram.user_id == user.id).first()
    if not diag: raise HTTPException(status_code=404, detail="Session not found.")
    return diag

@router.put("/{diagram_id}/", response_model=schemas.InteractiveDiagramOut)
def update_diagram_state(diagram_id: str, body: schemas.InteractiveDiagramUpdateIn, db: DbSession = Depends(get_db), user: models.User = Depends(auth.get_current_user)):
    diag = db.query(models.InteractiveDiagram).filter(models.InteractiveDiagram.id == diagram_id, models.InteractiveDiagram.user_id == user.id).first()
    if not diag: raise HTTPException(status_code=404, detail="Session not found.")
    diag.canvas_state = body.canvas_state
    db.commit()
    db.refresh(diag)
    return diag