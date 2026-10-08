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
        "CRITICAL ESCAPING RULES:\n"
        "1. You MUST use SINGLE QUOTES ('') for all HTML attributes and JavaScript strings inside `html_code`. NEVER use double quotes inside the HTML/JS string.\n"
        "2. Do NOT use literal raw newlines inside JSON string values. Keep code compressed or use escaped \\n.\n"
        "3. Inside your JavaScript, use window.parent.postMessage({ type: 'UPDATE_METRIC', title: 'Metric', value: 'Val' }, '*'); to send real-time stats."
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
        
        # If content is a dict already (returned by provider), validate keys
        if isinstance(content, dict) and "html_code" in content:
            return content

        # If content is a string, parse it defensively
        if isinstance(content, str) and len(content.strip()) > 0:
            clean_str = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
            try:
                parsed = json.loads(clean_str, strict=False)
                if isinstance(parsed, dict) and "html_code" in parsed:
                    return parsed
            except json.JSONDecodeError:
                logger.warning("Standard JSON parse failed. Extracting fields via regex fallback.")
                title_match = re.search(r'"title"\s*:\s*"(.*?)"', clean_str, re.DOTALL)
                desc_match = re.search(r'"description"\s*:\s*"(.*?)"', clean_str, re.DOTALL)
                lecture_match = re.search(r'"detailed_lecture"\s*:\s*"(.*?)"', clean_str, re.DOTALL)
                html_match = re.search(r'"html_code"\s*:\s*"(.*)"\s*\}?\s*$', clean_str, re.DOTALL)
                
                if html_match:
                    return {
                        "title": title_match.group(1) if title_match else body.topic.title(),
                        "description": desc_match.group(1) if desc_match else f"Interactive model for {body.topic}",
                        "detailed_lecture": lecture_match.group(1) if lecture_match else "Detailed lecture analysis unavailable.",
                        "html_code": html_match.group(1).encode().decode('unicode-escape')
                    }

        raise ValueError("Invalid or empty content structure returned from LLM pipeline.")

    except Exception as e:
        logger.warning(f"LLM Generation/Parsing encountered an issue ({e}). Serving robust dynamic fallback for: {body.topic}")
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
    <p>Loaded robust local simulation loop.</p>
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
    if not diag: raise HTTPException(status_url=404, detail="Session not found.")
    return diag

@router.put("/{diagram_id}/", response_model=schemas.InteractiveDiagramOut)
def update_diagram_state(diagram_id: str, body: schemas.InteractiveDiagramUpdateIn, db: DbSession = Depends(get_db), user: models.User = Depends(auth.get_current_user)):
    diag = db.query(models.InteractiveDiagram).filter(models.InteractiveDiagram.id == diagram_id, models.InteractiveDiagram.user_id == user.id).first()
    if not diag: raise HTTPException(status_code=404, detail="Session not found.")
    diag.canvas_state = body.canvas_state
    db.commit()
    db.refresh(diag)
    return diag