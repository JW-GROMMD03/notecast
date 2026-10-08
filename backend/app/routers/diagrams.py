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


@router.post("/generate-sim")
async def generate_simulation_schema(
    body: GenerateSimIn,
    user: models.User = Depends(auth.get_current_user)
):
    """
    Uses the multi-LLM pipeline (Gemini/Groq/DeepSeek) to generate a dynamic 
    interactive 3D simulation schema JSON for any academic unit, concept, or topic.
    """
    system_prompt = (
        "You are an expert academic architectural engineer and educational visualizer. "
        "Create a 3D simulation JSON schema for the requested topic. "
        "Output ONLY valid JSON with NO markdown formatting. Format exactly like this:\n"
        "{\n"
        '  "title": "String",\n'
        '  "description": "String",\n'
        '  "detailed_lecture": "Extremely detailed, degree-level lecture text explaining every biological, physical, or technical process involved. Do not summarize. Use HTML tags like <strong> and <br> for formatting.",\n'
        '  "nodes": [\n'
        '    { "id": "n1", "label": "Name", "x": -4, "y": 0, "z": 0, "color": "#hex", "shape_3d": "organic|sphere|tube|cube" }\n'
        '  ],\n'
        '  "edges": [\n'
        '    { "from": "n1", "to": "n2", "particle_color": "#hex", "label": "Process name" }\n'
        '  ],\n'
        '  "parameters": [\n'
        '    { "id": "p1", "label": "Name", "type": "slider", "min": 1, "max": 10, "default": 5 },\n'
        '    { "id": "p2", "label": "Condition Type", "type": "select", "options": ["Option A", "Option B", "Option C"], "default": "Option A" }\n'
        '  ]\n'
        "}\n"
        "Rules:\n"
        "- Nodes MUST include x, y, and z coordinates for 3D space placement (values between -5 and 5).\n"
        "- `shape_3d` must be one of: 'organic' (for stomachs/cells/organs), 'tube' (for intestines/pipes), 'sphere' (for planets), or 'cube' (for servers/systems).\n"
        "- Provide at least 3 parameters, mixing 'slider' and 'select' types to allow deep system control."
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
            # Clean up potential markdown code block artifacts from LLM outputs
            clean_str = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
            content = json.loads(clean_str)
            
        return content
    except Exception as e:
        logger.error(f"Failed to generate dynamic simulation schema: {e}")
        raise HTTPException(status_code=500, detail="Could not generate 3D simulation layout for this topic.")


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


@router.get("/{diagram_id}", response_model=schemas.InteractiveDiagramOut)
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


@router.put("/{diagram_id}", response_model=schemas.InteractiveDiagramOut)
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