import logging
import json
import re
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
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
    Instructs the LLM pipeline to generate a complete, self-contained, 
    stunning interactive HTML/CSS/JS simulation application tailored to ANY topic.
    """
    system_prompt = (
        "You are an elite senior frontend engineer and visual academic educator. "
        "Create a complete, self-contained, stunning interactive HTML/CSS/JS animation and simulation application for the requested topic. "
        "Output ONLY valid JSON with NO markdown formatting. Format exactly like this:\n"
        "{\n"
        "  \"title\": \"Topic Title\",\n"
        "  \"description\": \"Short subtitle description\",\n"
        "  \"detailed_lecture\": \"Extremely detailed, degree-level academic lecture text explaining the topic. Use HTML tags like <strong> and <br> for professional formatting.\",\n"
        "  \"html_code\": \"<!DOCTYPE html><html><head><style>/* CSS styles */</style></head><body><!-- Use SINGLE QUOTES for HTML attributes --> <script>/* JavaScript logic */</script></body></html>\"\n"
        "}\n\n"
        "CRITICAL JSON ESCAPING RULES:\n"
        "1. You MUST use SINGLE QUOTES ('') for all HTML attributes and JavaScript strings inside `html_code` (e.g., `<div id='app' class='container'>`). NEVER use double quotes inside the HTML/JS string.\n"
        "2. Do NOT use literal raw newlines inside the `html_code` JSON string values. Keep the HTML code compressed on single lines or use escaped `\\n`.\n"
        "3. ADVANCED METRICS: Inside your generated JavaScript, use window.parent.postMessage({ type: 'UPDATE_METRIC', title: 'Metric Name', value: 'Value' }, '*'); to send real-time stats to the UI."
    )

    try:
        logger.info(f"Initiating dynamic simulation generation for topic: {body.topic}")
        response = await providers.llm_chat_completion(
            capability="text",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Generate a stunning interactive HTML/JS simulation application for: {body.topic}"}
            ]
        )
        
        content = response.get("content", {})
        if isinstance(content, str):
            clean_str = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
            # strict=False allows the parser to tolerate minor whitespace/newline formatting issues from the LLM
            content = json.loads(clean_str, strict=False)
            
        return content

    except Exception as e:
        logger.error(f"LLM Provider Failed. Utilizing Dynamic HTML Fallback for {body.topic}: {e}")
        safe_topic = body.topic.title().replace('"', '').replace("'", "")
        return {
            "title": f"{safe_topic} — Interactive Visualizer",
            "description": f"Custom interactive visual model for {safe_topic}.",
            "detailed_lecture": f"<strong>Degree-Level Analysis: {safe_topic}</strong><br><br>This system operates through coordinated component interactions and state transitions. Use the interactive controls within the visualizer to test throughput, scaling, and operational workflows in real time.",
            "html_code": f"""<!DOCTYPE html>
<html lang='en'>
<head>
<meta charset='utf-8'>
<style>
  body {{ margin: 0; background: #030712; color: #fff; font-family: -apple-system, BlinkMacSystemFont, sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; overflow: hidden; }}
  .card {{ background: #0f172a; border: 1px solid #1e293b; padding: 35px; border-radius: 16px; text-align: center; box-shadow: 0 15px 35px rgba(0,0,0,0.6); max-width: 480px; width: 90%; }}
  h2 {{ color: #3b82f6; margin-top: 0; font-size: 1.4rem; }}
  p {{ color: #94a3b8; font-size: 0.9rem; line-height: 1.5; }}
  .sim-view {{ margin: 20px auto; width: 100px; height: 100px; border-radius: 50%; background: radial-gradient(circle, #3b82f6 0%, #1e293b 80%); box-shadow: 0 0 20px rgba(59, 130, 246, 0.5); transition: transform 0.2s ease; }}
  .btn-group {{ display: flex; gap: 10px; justify-content: center; margin-top: 25px; }}
  button {{ background: #3b82f6; color: white; border: none; padding: 12px 24px; border-radius: 8px; font-weight: 600; cursor: pointer; transition: 0.2s; }}
  button:hover {{ background: #2563eb; transform: translateY(-1px); }}
</style>
</head>
<body>
  <div class='card'>
    <h2>{safe_topic}</h2>
    <p>AI generation rate-limited. Loaded robust local fallback loop.</p>
    <div class='sim-view' id='simObject'></div>
    <div class='btn-group'>
      <button onclick='runPulse()'>Trigger State Pulse</button>
      <button onclick='resetSim()' style='background: #1e293b; color: #cbd5e1;'>Reset</button>
    </div>
  </div>
  <script>
    let count = 0;
    function runPulse() {{
      count++;
      const obj = document.getElementById('simObject');
      obj.style.transform = 'scale(1.2)';
      setTimeout(() => obj.style.transform = 'scale(1)', 200);
      window.parent.postMessage({{ type: 'UPDATE_METRIC', title: 'Execution Cycles', value: count }}, '*');
      window.parent.postMessage({{ type: 'UPDATE_METRIC', title: 'System Status', value: 'Active' }}, '*');
    }}
    function resetSim() {{
      count = 0;
      window.parent.postMessage({{ type: 'UPDATE_METRIC', title: 'Execution Cycles', value: count }}, '*');
      window.parent.postMessage({{ type: 'UPDATE_METRIC', title: 'System Status', value: 'Standby' }}, '*');
    }}
    resetSim();
  </script>
</body>
</html>"""
        }

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