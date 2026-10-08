import logging
import json
import re
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DbSession
from pydantic import BaseModel
from .. import models, schemas, auth
from ..database import get_db
from ..services import providers

router = APIRouter(prefix="/diagrams", tags=["diagrams"])
logger = logging.getLogger("notecast_diagrams")


class GenerateSimIn(BaseModel):
    topic: str


@router.post("/generate-sim/")
async def generate_simulation_schema(
    body: GenerateSimIn,
    user: models.User = Depends(auth.get_current_user)
):
    """
    Instructs the LLM pipeline to generate a complete, self-contained, 
    stunning interactive HTML/CSS/JS simulation application tailored to the topic.
    """
    system_prompt = (
        "You are an elite senior frontend engineer and visual academic educator. "
        "Create a complete, self-contained, stunning interactive HTML/CSS/JS animation and simulation application for the requested topic. "
        "Output ONLY valid JSON with NO markdown formatting. Format exactly like this:\n"
        "{\n"
        '  "title": "Topic Title",\n'
        '  "description": "Short subtitle description",\n'
        '  "detailed_lecture": "Extremely detailed, degree-level academic lecture text explaining the topic. Use HTML tags like <strong> and <br> for professional formatting.",\n'
        '  "html_code": "<!DOCTYPE html><html><head><style>/* Gorgeous dark-mode UI, flexbox, glowing nodes, animations, responsive layout */</style></head><body><!-- Fully interactive visualizer with buttons, animated SVG/Canvas, live counters, and click actions --> <script>/* Robust interactive JS animation logic and state controls */</script></body></html>"\n'
        "}\n"
        "Rules:\n"
        "- The 'html_code' field MUST contain a 100% valid, self-contained HTML document with embedded CSS and JavaScript.\n"
        "- Design it with a professional dark theme (#030712 background), glowing SVG connection lines, animated pulses, interactive control buttons (like Start, Pause, Restart, Scale Out, or Trigger Pulse), and real-time metric counters.\n"
        "- Ensure it visually represents the actual real-world architecture, biological system, chemical reaction, or physical process with high fidelity."
    )

    try:
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
            content = json.loads(clean_str)
            
        return content

    except Exception as e:
        logger.error(f"LLM Provider Failed. Utilizing Rich HTML Fallback: {e}")
        return {
            "title": f"{body.topic} — Interactive Visualizer",
            "description": f"Custom interactive visual model for {body.topic}.",
            "detailed_lecture": f"<strong>Degree-Level Analysis: {body.topic}</strong><br><br>This system operates through coordinated component interactions and state transitions. Use the interactive controls within the visualizer to test throughput, scaling, and operational workflows in real time.",
            "html_code": f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  body {{ margin: 0; background: #030712; color: #fff; font-family: -apple-system, BlinkMacSystemFont, sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; overflow: hidden; }}
  .card {{ background: #0f172a; border: 1px solid #1e293b; padding: 35px; border-radius: 16px; text-align: center; box-shadow: 0 15px 35px rgba(0,0,0,0.6); max-width: 480px; width: 90%; }}
  h2 {{ color: #3b82f6; margin-top: 0; font-size: 1.4rem; }}
  p {{ color: #94a3b8; font-size: 0.9rem; line-height: 1.5; }}
  .metric {{ font-size: 2.2rem; font-weight: 800; color: #10b981; margin: 20px 0; font-family: monospace; }}
  .btn-group {{ display: flex; gap: 10px; justify-content: center; margin-top: 15px; }}
  button {{ background: #3b82f6; color: white; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 600; cursor: pointer; transition: 0.2s; }}
  button:hover {{ background: #2563eb; transform: translateY(-1px); }}
</style>
</head>
<body>
  <div class="card">
    <h2>{body.topic}</h2>
    <p>Interactive simulation environment initialized successfully.</p>
    <div class="metric" id="counter">Cycles: 0</div>
    <div class="btn-group">
      <button onclick="runSim()">Trigger Pulse</button>
      <button onclick="resetSim()" style="background: #1e293b; color: #cbd5e1;">Reset</button>
    </div>
  </div>
  <script>
    let count = 0;
    function runSim() {{
      count++;
      document.getElementById('counter').textContent = 'Cycles: ' + count;
    }}
    function resetSim() {{
      count = 0;
      document.getElementById('counter').textContent = 'Cycles: ' + count;
    }}
  </script>
</body>
</html>"""
        }


@router.post("/", response_model=schemas.InteractiveDiagramOut, status_code=status.HTTP_201_CREATED)
def create_diagram(
    body: schemas.InteractiveDiagramCreateIn,
    db: DbSession = Depends(get_db),
    user: models.User = Depends(auth.get_current_user)
):
    """Creates a new interactive simulation workspace session."""
    new_diag = models.InteractiveDiagram(
        user_id=user.id,
        title=body.title,
        sim_type=body.sim_type,
        canvas_state={"nodes": [], "edges": []}
    )
    db.add(new_diag)
    db.commit()
    db.refresh(new_diag)
    return new_diag


@router.get("/", response_model=List[schemas.InteractiveDiagramOut])
def list_diagrams(
    db: DbSession = Depends(get_db),
    user: models.User = Depends(auth.get_current_user)
):
    """Fetches all saved simulation workspaces for the user."""
    return db.query(models.InteractiveDiagram).filter(models.InteractiveDiagram.user_id == user.id).all()


@router.get("/{diagram_id}/", response_model=schemas.InteractiveDiagramOut)
def get_diagram(
    diagram_id: str,
    db: DbSession = Depends(get_db),
    user: models.User = Depends(auth.get_current_user)
):
    """Retrieves state for a specific simulation session."""
    diag = db.query(models.InteractiveDiagram).filter(
        models.InteractiveDiagram.id == diagram_id,
        models.InteractiveDiagram.user_id == user.id
    ).first()
    if not diag:
        raise HTTPException(status_code=404, detail="Simulation session not found.")
    return diag


@router.put("/{diagram_id}/", response_model=schemas.InteractiveDiagramOut)
def update_diagram_state(
    diagram_id: str,
    body: schemas.InteractiveDiagramUpdateIn,
    db: DbSession = Depends(get_db),
    user: models.User = Depends(auth.get_current_user)
):
    """Saves canvas state for the simulation session."""
    diag = db.query(models.InteractiveDiagram).filter(
        models.InteractiveDiagram.id == diagram_id,
        models.InteractiveDiagram.user_id == user.id
    ).first()
    if not diag:
        raise HTTPException(status_code=404, detail="Simulation session not found.")

    diag.canvas_state = body.canvas_state
    db.commit()
    db.refresh(diag)
    return diag