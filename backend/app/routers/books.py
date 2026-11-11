import os
import boto3
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query
from sqlalchemy.orm import Session
from typing import Optional

from .. import models, auth
from ..database import get_db

router = APIRouter(prefix="", tags=["Book Library & R2 Storage"])

# --- CLOUDFLARE R2 S3 CLIENT CONFIGURATION ---
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "your_r2_access_key")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "your_r2_secret_key")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "notecast-books")
R2_ENDPOINT_URL = os.getenv(
    "R2_ENDPOINT_URL",
    "https://<YOUR_ACCOUNT_ID>.r2.cloudflarestorage.com",
)
R2_PUBLIC_DOMAIN = os.getenv(
    "R2_PUBLIC_DOMAIN", "https://pub-xxx.r2.dev"
)

s3_client = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT_URL,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
)


@router.post("/admin/books/upload/")
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
    """Uploads a textbook document & optional cover image to Cloudflare R2 and records metadata in PostgreSQL."""
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
        raise HTTPException(
            status_code=500, detail=f"Document R2 Storage Upload Failed: {str(e)}"
        )
    document_url = f"{R2_PUBLIC_DOMAIN}/{doc_key}"

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
            cover_url = f"{R2_PUBLIC_DOMAIN}/{cover_key}"
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Cover Image R2 Upload Failed: {str(e)}"
            )

    # 3. Construct record for PostgreSQL / Supabase 'books' table
    new_book = models.Book(
        title=title,
        course=course,
        unit=unit,
        price=price,
        file_url=document_url,
        cover_url=cover_url,
        user_id=admin.id
    )
    
    db.add(new_book)
    db.commit()
    db.refresh(new_book)

    return {
        "status": "SUCCESS",
        "message": "Book and details uploaded successfully to Cloudflare R2",
        "book_id": new_book.id
    }


@router.get("/books/store")
def get_book_store(
    course: Optional[str] = Query(None, description="Filter by course name"),
    unit: Optional[str] = Query(None, description="Filter by unit/module"),
    db: Session = Depends(get_db)
):
    """Fetches filtered books from the database for the frontend user library catalog."""
    query = db.query(models.Book)
    
    if course:
        query = query.filter(models.Book.course.ilike(f"%{course}%"))
    if unit:
        query = query.filter(models.Book.unit.ilike(f"%{unit}%"))
        
    books = query.order_by(models.Book.created_at.desc()).all()
    
    return [{
        "id": b.id,
        "title": b.title,
        "course": getattr(b, "course", "General") or "General",
        "unit": getattr(b, "unit", "General") or "General",
        "price": b.price,
        "cover_url": getattr(b, "cover_url", getattr(b, "cover_photo_url", None))
    } for b in books]