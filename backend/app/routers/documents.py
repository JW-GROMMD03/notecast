import os
import uuid
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session as DbSession
from .. import models, schemas, auth
from ..database import get_db
from ..config import settings

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger("notecast_documents")


@router.post("/upload/", response_model=schemas.DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: DbSession = Depends(get_db),
    user: models.User = Depends(auth.get_current_user)
):
    """Accepts PDF study files, saves them to disk, and registers them in the database."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF documents are supported currently.")

    os.makedirs(settings.storage_path, exist_ok=True)
    doc_id = f"doc_{uuid.uuid4().hex[:12]}"
    file_ext = os.path.splitext(file.filename)[1]
    storage_filename = f"{doc_id}{file_ext}"
    file_path = os.path.join(settings.storage_path, storage_filename)

    try:
        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)
    except Exception as e:
        logger.error(f"Failed to save document file: {e}")
        raise HTTPException(status_code=500, detail="Could not store uploaded document.")

    new_doc = models.Document(
        id=doc_id,
        user_id=user.id,
        title=os.path.splitext(file.filename)[0],
        filename=file.filename,
        storage_key=storage_filename,
        status="ready"
    )
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)

    return new_doc


@router.get("/", response_model=List[schemas.DocumentOut])
def list_documents(
    db: DbSession = Depends(get_db),
    user: models.User = Depends(auth.get_current_user)
):
    """Lists all uploaded reading materials and study guides."""
    return db.query(models.Document).filter(models.Document.user_id == user.id).all()


@router.get("/media/{storage_key}/")
def get_document_media(
    storage_key: str,
    db: DbSession = Depends(get_db),
    user: models.User = Depends(auth.get_current_user)
):
    """Directly streams the PDF binary for the frontend document viewer iframe."""
    doc = db.query(models.Document).filter(
        models.Document.storage_key == storage_key,
        models.Document.user_id == user.id
    ).first()
    
    if not doc:
        raise HTTPException(status_code=404, detail="Document file not found or unauthorized.")
        
    file_path = os.path.join(settings.storage_path, storage_key)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Physical file missing on server storage.")
        
    return FileResponse(file_path, media_type="application/pdf", filename=doc.filename)


@router.get("/{doc_id}/", response_model=schemas.DocumentOut)
def get_document(
    doc_id: str,
    db: DbSession = Depends(get_db),
    user: models.User = Depends(auth.get_current_user)
):
    """Retrieves document processing status and synthesized study guides."""
    doc = db.query(models.Document).filter(
        models.Document.id == doc_id,
        models.Document.user_id == user.id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc


@router.get("/{doc_id}/pages/{page_number}/")
def get_document_page_cache(
    doc_id: str,
    page_number: int,
    db: DbSession = Depends(get_db),
    user: models.User = Depends(auth.get_current_user)
):
    """Checks if a specific page snapshot and summary are cached in the database."""
    doc = db.query(models.Document).filter(
        models.Document.id == doc_id,
        models.Document.user_id == user.id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    
    page = db.query(models.DocumentPage).filter(
        models.DocumentPage.document_id == doc_id,
        models.DocumentPage.page_number == page_number
    ).first()
    
    if not page:
        return {"cached": False, "page_number": page_number}
    
    return {
        "cached": True,
        "page_number": page_number,
        "ai_analysis": page.ai_analysis,
        "ocr_text": page.ocr_text
    }