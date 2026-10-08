import logging
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DbSession
from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/graph", tags=["graph"])
logger = logging.getLogger("notecast_graph")


@router.get("/", response_model=Dict[str, Any])
def get_full_graph(
    db: DbSession = Depends(get_db),
    user: models.User = Depends(auth.get_current_user)
):
    """
    Returns the complete knowledge graph for the user, 
    formatted perfectly for frontend node-web visualization libraries.
    """
    nodes = db.query(models.KnowledgeNode).filter(models.KnowledgeNode.user_id == user.id).all()
    edges = db.query(models.KnowledgeEdge).filter(models.KnowledgeEdge.user_id == user.id).all()
    
    return {
        "nodes": [schemas.KnowledgeNodeOut.model_validate(n).model_dump() for n in nodes],
        "edges": [schemas.KnowledgeEdgeOut.model_validate(e).model_dump() for e in edges]
    }


@router.post("/nodes", response_model=schemas.KnowledgeNodeOut, status_code=status.HTTP_201_CREATED)
def create_node(
    body: schemas.KnowledgeNodeCreateIn,
    db: DbSession = Depends(get_db),
    user: models.User = Depends(auth.get_current_user)
):
    """Creates a new concept node (Triggered by AI extraction from notes or PDFs)."""
    new_node = models.KnowledgeNode(
        user_id=user.id,
        concept_name=body.concept_name,
        description_md=body.description_md,
        source_references=body.source_references
    )
    db.add(new_node)
    db.commit()
    db.refresh(new_node)
    return new_node


@router.post("/edges", response_model=schemas.KnowledgeEdgeOut, status_code=status.HTTP_201_CREATED)
def create_edge(
    body: schemas.KnowledgeEdgeCreateIn,
    db: DbSession = Depends(get_db),
    user: models.User = Depends(auth.get_current_user)
):
    """Draws a relationship link between two existing concepts."""
    source = db.query(models.KnowledgeNode).filter(models.KnowledgeNode.id == body.source_node_id, models.KnowledgeNode.user_id == user.id).first()
    target = db.query(models.KnowledgeNode).filter(models.KnowledgeNode.id == body.target_node_id, models.KnowledgeNode.user_id == user.id).first()
    
    if not source or not target:
        raise HTTPException(status_code=400, detail="Source or target node does not exist in your graph.")
        
    new_edge = models.KnowledgeEdge(
        user_id=user.id,
        source_node_id=body.source_node_id,
        target_node_id=body.target_node_id,
        relationship_type=body.relationship_type,
        weight=body.weight
    )
    db.add(new_edge)
    db.commit()
    db.refresh(new_edge)
    return new_edge