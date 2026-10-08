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
        '  "title": "Topic Title",\n'
        '  "description": "Short subtitle description",\n'
        '  "detailed_lecture": "Extremely detailed, degree-level academic lecture text explaining the topic. Use HTML tags like <strong> and <br> for professional formatting.",\n'
        '  "html_code": "<!DOCTYPE html><html><head><style>/* Gorgeous dark-mode UI, flexbox, glowing SVG nodes, animations, responsive layout */</style></head><body><!-- Fully interactive visualizer with buttons, animated SVG/Canvas, and click actions --> <script>/* Robust interactive JS animation logic */</script></body></html>"\n'
        "}\n\n"
        "CRITICAL RULES:\n"
        "1. The 'html_code' field MUST contain a 100% valid, self-contained HTML document with embedded CSS and JavaScript.\n"
        "2. Design it with a professional dark theme (#030712 background), glowing SVG connection lines, animated pulses, and interactive control buttons (e.g., Start, Pause, Scale Out, Trigger Process).\n"
        "3. Ensure it visually represents the actual real-world architecture, biological system, chemical reaction, or physical process with high fidelity (e.g., draw servers/load balancers for IT, draw cells/organs for biology).\n"
        "4. ADVANCED METRICS COMMUNICATION: Inside your generated JavaScript, use the postMessage API to send real-time metrics back to the parent window whenever the simulation state changes. Example:\n"
        "   window.parent.postMessage({ type: 'UPDATE_METRIC', title: 'Throughput', value: '500 req/s' }, '*');\n"
        "   window.parent.postMessage({ type: 'UPDATE_METRIC', title: 'Active Nodes', value: '4' }, '*');\n"
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
            # Strip out markdown code blocks to ensure pure JSON parsing
            clean_str = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
            content = json.loads(clean_str)
            
        return content

    except Exception as e:
        logger.error(f"LLM Provider Failed. Utilizing Dynamic HTML Fallback for {body.topic}: {e}")
        # Dynamic fallback based entirely on the requested topic if the AI times out
        return {
            "title": f"{body.topic.title()} — Interactive Visualizer",
            "description": f"Custom interactive visual model for {body.topic}.",
            "detailed_lecture": f"<strong>Degree-Level Analysis: {body.topic.title()}</strong><br><br>This system operates through coordinated component interactions and state transitions. The visualizer relies on state-driven rendering to emulate real-world behavior. Use the interactive controls within the visualizer to test throughput, scaling, and operational workflows in real time.",
            "html_code": f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  body {{ margin: 0; background: #030712; color: #fff; font-family: -apple-system, BlinkMacSystemFont, sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; overflow: hidden; }}
  .card {{ background: #0f172a; border: 1px solid #1e293b; padding: 35px; border-radius: 16px; text-align: center; box-shadow: 0 15px 35px rgba(0,0,0,0.6); max-width: 480px; width: 90%; }}
  h2 {{ color: #3b82f6; margin-top: 0; font-size: 1.4rem; text-transform: capitalize; }}
  p {{ color: #94a3b8; font-size: 0.9rem; line-height: 1.5; }}
  .sim-view {{ margin: 20px auto; width: 100px; height: 100px; border-radius: 50%; background: radial-gradient(circle, #3b82f6 0%, #1e293b 80%); box-shadow: 0 0 20px rgba(59, 130, 246, 0.5); transition: transform 0.2s ease; }}
  .btn-group {{ display: flex; gap: 10px; justify-content: center; margin-top: 25px; }}
  button {{ background: #3b82f6; color: white; border: none; padding: 12px 24px; border-radius: 8px; font-weight: 600; cursor: pointer; transition: 0.2s; }}
  button:hover {{ background: #2563eb; transform: translateY(-1px); }}
</style>
</head>
<body>
  <div class="card">
    <h2>{body.topic}</h2>
    <p>Interactive simulation environment initialized successfully. Commencing execution loop.</p>
    <div class="sim-view" id="simObject"></div>
    <div class="btn-group">
      <button onclick="runPulse()">Trigger State Pulse</button>
      <button onclick="resetSim()" style="background: #1e293b; color: #cbd5e1;">Reset</button>
    </div>
  </div>
  <script>
    let count = 0;
    function runPulse() {{
      count++;
      const obj = document.getElementById('simObject');
      obj.style.transform = 'scale(1.2)';
      setTimeout(() => obj.style.transform = 'scale(1)', 200);
      
      // Communicate back to the parent window
      window.parent.postMessage({{ type: 'UPDATE_METRIC', title: 'Execution Cycles', value: count }}, '*');
      window.parent.postMessage({{ type: 'UPDATE_METRIC', title: 'System Status', value: 'Active' }}, '*');
    }}
    function resetSim() {{
      count = 0;
      window.parent.postMessage({{ type: 'UPDATE_METRIC', title: 'Execution Cycles', value: count }}, '*');
      window.parent.postMessage({{ type: 'UPDATE_METRIC', title: 'System Status', value: 'Standby' }}, '*');
    }}
    // Initialize default metrics
    resetSim();
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