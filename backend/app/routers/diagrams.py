import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DbSession
from .. import models, schemas, auth
from ..database import get_db
from ..services import providers

router = APIRouter(prefix="/diagrams", tags=["diagrams"])
logger = logging.getLogger("notecast_diagrams")


@router.post("/", response_model=schemas.InteractiveDiagramOut, status_code=status.HTTP_201_CREATED)
async def create_diagram(
    body: schemas.InteractiveDiagramCreateIn,
    db: DbSession = Depends(get_db),
    user: models.User = Depends(auth.get_current_user)
):
    """Creates a new diagram session, optionally generating initial canvas nodes via AI."""
    initial_state = {
        "nodes": [],
        "edges": [],
        "viewport": {"x": 0, "y": 0, "zoom": 1.0}
    }

    # Prompt-to-Diagram Generator
    if body.prompt and body.prompt.strip():
        system_prompt = (
            "You are an expert system architect and visual designer. "
            "Convert the user's concept into a structured canvas graph JSON with 'nodes' and 'edges'. "
            "Output ONLY valid JSON containing 'nodes' (id, label, type, x, y) and 'edges' (id, source, target, label)."
        )
        try:
            ai_res = await providers.llm_chat_completion(
                capability="text",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": body.prompt}
                ]
            )
            # Basic validation of returned structure
            if "nodes" in ai_res.get("content", {}) and "edges" in ai_res.get("content", {}):
                initial_state["nodes"] = ai_res["content"]["nodes"]
                initial_state["edges"] = ai_res["content"]["edges"]
        except Exception as e:
            logger.warning(f"AI diagram generation fell back to empty canvas: {e}")

    new_diagram = models.InteractiveDiagram(
        user_id=user.id,
        title=body.title,
        sim_type=body.sim_type,
        canvas_state=initial_state,
        prompt_history=[body.prompt] if body.prompt else []
    )
    db.add(new_diagram)
    db.commit()
    db.refresh(new_diagram)
    return new_diagram


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