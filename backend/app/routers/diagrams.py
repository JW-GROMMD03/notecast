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
    interactive simulation schema JSON for any academic unit, concept, or topic.
    """
    system_prompt = (
        "You are an expert educational visualizer and simulation engineer. "
        "Create an interactive system simulation schema for the user's requested topic. "
        "Output ONLY a raw JSON object with NO markdown formatting, no backticks. Structure:\n"
        "{\n"
        '  "title": "Title",\n'
        '  "description": "Short explanation",\n'
        '  "nodes": [{"id": "n1", "label": "Node 1", "x_pct": 20, "y_pct": 50, "color": "#3b82f6"}],\n'
        '  "edges": [{"from": "n1", "to": "n2", "particle_color": "#a855f7", "label": "Flow"}],\n'
        '  "parameters": [{"id": "p1", "label": "Rate", "min": 1, "max": 30, "default": 5}]\n'
        "}"
    )

    try:
        response = await providers.llm_chat_completion(
            capability="text",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Generate simulation for: {body.topic}"}
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
        raise HTTPException(status_code=500, detail="Could not generate simulation layout for this topic.")


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