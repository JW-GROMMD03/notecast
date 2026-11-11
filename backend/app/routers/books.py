import os
import boto3
import logging
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query
from sqlalchemy.orm import Session
from typing import Optional

from .. import models, auth
from ..database import get_db

router = APIRouter(prefix="/books", tags=["Book Library & R2 Storage"])
logger = logging.getLogger("notecast_books")

# --- CLOUDFLARE R2 S3 CLIENT CONFIGURATION ---
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "notecast-books")
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL", "")
R2_PUBLIC_DOMAIN = os.getenv("R2_PUBLIC_DOMAIN", "").rstrip("/")

s3_client = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT_URL or None,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
)


@router.post("/admin/upload/")
async def admin_upload_book(
    title: str = Form(...),
    course: str = Form(...),
    unit: str = Form(...),
    price: float = Form(...),
    description: str = Form(""),
    file: UploadFile = File(...), 
    cover_file: UploadFile = File(None),
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.get_current_admin)
):
    """Uploads textbook document & optional cover image to Cloudflare R2 and records absolute URLs."""
    allowed_doc_extensions = (".pdf", ".docx", ".doc")
    if not file.filename.lower().endswith(allowed_doc_extensions):
        raise HTTPException(
            status_code=400,
            detail="Invalid document format. Allowed: PDF, DOCX, DOC.",
        )

    # 1. Upload document file to Cloudflare R2
    doc_key = f"books/documents/{course}/{unit}/{file.filename}"
    try:
        s3_client.upload_fileobj(
            file.file,
            R2_BUCKET_NAME,
            doc_key,
            ExtraArgs={"ContentType": file.content_type},
        )
    except Exception as e:
        logger.error(f"Document R2 Storage Upload Failed: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Document R2 Storage Upload Failed: {str(e)}"
        )
    
    # Bulletproof absolute URL construction
    if R2_PUBLIC_DOMAIN and R2_PUBLIC_DOMAIN.startswith("http"):
        document_url = f"{R2_PUBLIC_DOMAIN}/{doc_key}"
    else:
        endpoint_clean = R2_ENDPOINT_URL.replace("https://", "").replace("http://", "").rstrip("/") if R2_ENDPOINT_URL else "r2.cloudflarestorage.com"
        document_url = f"https://{R2_BUCKET_NAME}.{endpoint_clean}/{doc_key}"

    # 2. Upload cover image to Cloudflare R2 (if provided)
    cover_url = None
    if cover_file:
        cover_key = f"books/covers/{course}/{unit}/{cover_file.filename}"
        try:
            s3_client.upload_fileobj(
                cover_file.file,
                R2_BUCKET_NAME,
                cover_key,
                ExtraArgs={"ContentType": cover_file.content_type},
            )
            if R2_PUBLIC_DOMAIN and R2_PUBLIC_DOMAIN.startswith("http"):
                cover_url = f"{R2_PUBLIC_DOMAIN}/{cover_key}"
            else:
                endpoint_clean = R2_ENDPOINT_URL.replace("https://", "").replace("http://", "").rstrip("/") if R2_ENDPOINT_URL else "r2.cloudflarestorage.com"
                cover_url = f"https://{R2_BUCKET_NAME}.{endpoint_clean}/{cover_key}"
        except Exception as e:
            logger.error(f"Cover Image R2 Upload Failed: {str(e)}")

    # 3. Save to database handling both model attribute naming styles
    book_kwargs = {
        "title": title,
        "course": course,
        "unit": unit,
        "price": price,
        "user_id": admin.id
    }
    
    # Dynamically assign URL fields based on what columns models.Book expects
    if hasattr(models.Book, "file_url"):
        book_kwargs["file_url"] = document_url
    if hasattr(models.Book, "book_file_url"):
        book_kwargs["book_file_url"] = document_url
        
    if cover_url:
        if hasattr(models.Book, "cover_url"):
            book_kwargs["cover_url"] = cover_url
        if hasattr(models.Book, "cover_photo_url"):
            book_kwargs["cover_photo_url"] = cover_url

    new_book = models.Book(**book_kwargs)
    db.add(new_book)
    db.commit()
    db.refresh(new_book)

    return {
        "status": "SUCCESS",
        "message": "Book uploaded successfully to Cloudflare R2",
        "book_id": new_book.id,
        "file_url": document_url,
        "cover_url": cover_url
    }


@router.get("/store")
def get_book_store(
    course: Optional[str] = Query(None, description="Filter by course name"),
    unit: Optional[str] = Query(None, description="Filter by unit/module"),
    db: Session = Depends(get_db)
):
    """Fetches books with guaranteed absolute URLs for viewing and downloading."""
    try:
        query = db.query(models.Book)
        
        if course:
            query = query.filter(models.Book.course.ilike(f"%{course}%"))
        if unit:
            query = query.filter(models.Book.unit.ilike(f"%{unit}%"))
            
        books = query.order_by(models.Book.created_at.desc()).all()
        
        results = []
        for b in books:
            f_url = getattr(b, "file_url", getattr(b, "book_file_url", None))
            c_url = getattr(b, "cover_url", getattr(b, "cover_photo_url", None))
            
            results.append({
                "id": b.id,
                "title": b.title,
                "course": getattr(b, "course", "General") or "General",
                "unit": getattr(b, "unit", "General") or "General",
                "price": b.price,
                "file_url": f_url,
                "cover_url": c_url
            })
            
        results.reverse()
        return results
    except Exception as e:
        logger.error(f"Failed to fetch book store inventory: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to load book store inventory.")