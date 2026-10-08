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
    Uses the multi-LLM pipeline (Gemini/Groq/DeepSeek) to generate a dynamic 
    interactive 3D simulation schema JSON for any academic course, anatomical system, or technical topic.
    """
    system_prompt = (
        "You are an expert academic architectural engineer and anatomical visualizer. "
        "Create a rigorous 3D simulation JSON schema for the requested topic. "
        "Output ONLY valid JSON with NO markdown formatting. Format exactly like this:\n"
        "{\n"
        '  "title": "String",\n'
        '  "description": "String",\n'
        '  "detailed_lecture": "Extremely detailed, degree-level lecture text explaining every biological, physical, or technical process in full detail. Use HTML tags like <strong> and <br> for formatting.",\n'
        '  "nodes": [\n'
        '    { "id": "n1", "label": "Anatomical Name", "x": 0, "y": 2, "z": 0, "color": "#hex", "shape_3d": "lung_left|lung_right|diaphragm|tube|sphere" }\n'
        '  ],\n'
        '  "edges": [\n'
        '    { "from": "n1", "to": "n2", "particle_color": "#hex", "label": "Process flow" }\n'
        '  ],\n'
        '  "parameters": [\n'
        '    { "id": "p1", "label": "State Control", "type": "select", "options": ["Option A", "Option B"], "default": "Option A" },\n'
        '    { "id": "p2", "label": "Frequency / Rate", "type": "slider", "min": 1, "max": 15, "default": 5 }\n'
        '  ]\n'
        "}\n"
        "Rules:\n"
        "- Nodes MUST include precise x, y, and z coordinates for 3D anatomical layout.\n"
        "- For biological systems, use realistic shape tags like 'lung_left', 'lung_right', 'diaphragm', 'tube', or 'sphere'.\n"
        "- Provide multiple parameters mixing 'select' dropdowns and 'slider' frequency controls so users can trigger real-time actions."
    )

    try:
        response = await providers.llm_chat_completion(
            capability="text",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Generate detailed 3D simulation for: {body.topic}"}
            ]
        )
        
        content = response.get("content", {})
        if isinstance(content, str):
            clean_str = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
            content = json.loads(clean_str)
            
        return content

    except Exception as e:
        logger.error(f"LLM Provider Failed (Keys/Timeout). Utilizing Dynamic Anatomical Fallback: {e}")
        return {
            "title": f"{body.topic} (Interactive 3D Simulation)",
            "description": f"Anatomical and systemic 3D interactive model for {body.topic}.",
            "detailed_lecture": f"<strong>Degree-Level Analysis: {body.topic}</strong><br><br>This system functions through continuous interdependent pathways. Matter, energy, or biological fluids originate at primary intake nodes and undergo regulated transformation.<br><br>Use the control panel on the right to manipulate state conditions (such as frequency, velocity, or operational modes) and observe real-time particle transfer across 3D pathways.",
            "nodes": [
              { "id": "n1", "label": "Primary Source", "x": -3, "y": 2, "z": 0, "color": "#3b82f6", "shape_3d": "sphere" },
              { "id": "n2", "label": "Central Processor", "x": 0, "y": 0, "z": 1, "color": "#f59e0b", "shape_3d": "sphere" },
              { "id": "n3", "label": "Terminal Receptor", "x": 3, "y": -2, "z": -1, "color": "#10b981", "shape_3d": "sphere" }
            ],
            "edges": [
              { "from": "n1", "to": "n2", "particle_color": "#ffffff", "label": "Primary Transport" },
              { "from": "n2", "to": "n3", "particle_color": "#38bdf8", "label": "Effector Pathway" }
            ],
            "parameters": [
              { "id": "p_mode", "label": "Operational Mode", "type": "select", "options": ["Standard", "High Output", "Resting"], "default": "Standard" },
              { "id": "p_freq", "label": "System Frequency", "type": "slider", "min": 1, "max": 10, "default": 5 }
            ]
        }


@router.post("/", response_model=schemas.InteractiveDiagramOut, status_code=status.HTTP_201_CREATED)
def create_diagram(
    body: schemas.InteractiveDiagramCreateIn,
    db: DbSession = Depends(get_db),
    user: models.User = Depends(auth.get_current_user)
):
    """Creates a new interactive diagram or simulation workspace session."""
    initial_state = {
        "nodes": [],
        "edges": [],
        "viewport": {"x": 0, "y": 0, "zoom": 1.0}
    }

    new_diag = models.InteractiveDiagram(
        user_id=user.id,
        title=body.title,
        sim_type=body.sim_type,
        canvas_state=initial_state
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
    """Fetches all saved diagrams and interactive simulators for the current user."""
    return db.query(models.InteractiveDiagram).filter(models.InteractiveDiagram.user_id == user.id).all()


@router.get("/{diagram_id}/", response_model=schemas.InteractiveDiagramOut)
def get_diagram(
    diagram_id: str,
    db: DbSession = Depends(get_db),
    user: models.User = Depends(auth.get_current_user)
):
    """Retrieves canvas state for a specific diagram or simulation session."""
    diag = db.query(models.InteractiveDiagram).filter(
        models.InteractiveDiagram.id == diagram_id,
        models.InteractiveDiagram.user_id == user.id
    ).first()
    if not diag:
        raise HTTPException(status_code=404, detail="Diagram session not found.")
    return diag


@router.put("/{diagram_id}/", response_model=schemas.InteractiveDiagramOut)
def update_diagram_state(
    diagram_id: str,
    body: schemas.InteractiveDiagramUpdateIn,
    db: DbSession = Depends(get_db),
    user: models.User = Depends(auth.get_current_user)
):
    """Saves node positions, parameter configurations, and connectors from the frontend studio."""
    diag = db.query(models.InteractiveDiagram).filter(
        models.InteractiveDiagram.id == diagram_id,
        models.InteractiveDiagram.user_id == user.id
    ).first()
    if not diag:
        raise HTTPException(status_code=404, detail="Diagram session not found.")

    diag.canvas_state = body.canvas_state
    db.commit()
    db.refresh(diag)
    return diag