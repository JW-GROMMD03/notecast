"""
routers/books.py - Full Production Book Store, Admin Management & R2 Storage Router
Note: R2 bucket remains PRIVATE. DB columns file_url / cover_url store R2 object keys.
"""
import logging
import os
import uuid
from typing import Optional, List

import boto3
from botocore.config import Config
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel, Field as PydanticField
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db

router = APIRouter(prefix="/books", tags=["Books"])
logger = logging.getLogger("notecast_books")

R2_BUCKET = os.getenv("R2_BUCKET_NAME", "notecast-books")
MIN_PRICE = 150  # Minimum book price in KES

# Initialize Cloudflare R2 / S3 Client
s3 = boto3.client(
    "s3",
    endpoint_url=os.getenv("R2_ENDPOINT_URL") or None,
    aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
    region_name="auto",
    config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
)

ALLOWED_DOC_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

ALLOWED_IMG_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


# --- Pydantic Schemas ---
class BookUpdatePayload(BaseModel):
    title: Optional[str] = None
    field: Optional[str] = None
    course: Optional[str] = None
    unit: Optional[str] = None
    price: Optional[float] = None
    description: Optional[str] = None


class BookPurchaseRequest(BaseModel):
    book_id: str
    phone_number: str


# --- Helper Functions ---
def _get_file_extension(filename: Optional[str]) -> str:
    if not filename:
        return ""
    return os.path.splitext(filename)[1].lower()


def _is_storage_key(value: Optional[str]) -> bool:
    return bool(value) and (value.startswith("books/") or "/" in value)


def verify_book_access(db: Session, user: models.User, book_id: str) -> bool:
    """Returns True if the user is an admin or has an active purchase record for the book."""
    if getattr(user, "is_admin", False):
        return True
    
    purchase = (
        db.query(models.BookPurchase)
        .filter(
            models.BookPurchase.user_id == user.id,
            models.BookPurchase.book_id == book_id,
            models.BookPurchase.status == "COMPLETED"
        )
        .first()
    )
    return purchase is not None


# =====================================================================
# 1. ADMIN UPLOAD & MANAGEMENT ENDPOINTS
# =====================================================================

@router.post("/admin/upload/")
@router.post("/api/books/admin/upload/")
def admin_upload_book(
    title: str = Form(...),
    field: str = Form("Technology"),
    course: str = Form(...),
    unit: str = Form("General"),
    price: float = Form(...),
    description: Optional[str] = Form(""),
    book_file: UploadFile = File(...),
    cover_photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.get_current_admin),
):
    """Admin endpoint to upload new study materials with Field & Course hierarchy."""
    if price < MIN_PRICE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Minimum book price is {MIN_PRICE} KES."
        )

    doc_ext = _get_file_extension(book_file.filename)
    if doc_ext not in ALLOWED_DOC_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid document format. Allowed types: PDF, DOC, DOCX."
        )

    has_cover = bool(cover_photo and cover_photo.filename)
    cover_ext = _get_file_extension(cover_photo.filename) if has_cover else ""
    if has_cover and cover_ext not in ALLOWED_IMG_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid cover image format. Allowed: JPG, PNG, WEBP."
        )

    doc_storage_key = f"books/documents/{uuid.uuid4().hex}{doc_ext}"
    cover_storage_key = f"books/covers/{uuid.uuid4().hex}{cover_ext}" if has_cover else None

    try:
        # Upload main document to R2
        s3.upload_fileobj(
            book_file.file,
            R2_BUCKET,
            doc_storage_key,
            ExtraArgs={"ContentType": ALLOWED_DOC_TYPES[doc_ext]}
        )
        
        # Upload cover photo if provided
        if cover_storage_key and cover_photo:
            s3.upload_fileobj(
                cover_photo.file,
                R2_BUCKET,
                cover_storage_key,
                ExtraArgs={"ContentType": ALLOWED_IMG_TYPES[cover_ext]}
            )
    except Exception as e:
        logger.exception("Cloudflare R2 upload transmission error: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Storage upload failed: {str(e)}"
        )

    try:
        new_book = models.Book(
            title=title.strip(),
            field=field.strip(),
            course=course.strip(),
            unit=(unit or "General").strip(),
            price=price,
            description=(description or "").strip(),
            file_url=doc_storage_key,
            cover_url=cover_storage_key,
            user_id=admin.id,
            status="ACTIVE"
        )
        db.add(new_book)
        db.commit()
        db.refresh(new_book)
    except Exception as db_err:
        db.rollback()
        logger.exception("Database persistence error during book upload: %s", str(db_err))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not persist book record in database."
        )

    return {
        "status": "SUCCESS",
        "message": "Book uploaded successfully",
        "book_id": new_book.id,
        "field": new_book.field,
        "course": new_book.course
    }


@router.put("/admin/{book_id}")
@router.put("/api/books/admin/{book_id}")
def admin_update_book(
    book_id: str,
    payload: BookUpdatePayload,
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.get_current_admin),
):
    """Updates book metadata, pricing, or academic hierarchy."""
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found.")

    if payload.title is not None:
        book.title = payload.title.strip()
    if payload.field is not None:
        book.field = payload.field.strip()
    if payload.course is not None:
        book.course = payload.course.strip()
    if payload.unit is not None:
        book.unit = payload.unit.strip()
    if payload.description is not None:
        book.description = payload.description.strip()
    if payload.price is not None:
        if payload.price < MIN_PRICE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Minimum price is {MIN_PRICE} KES."
            )
        book.price = payload.price

    db.commit()
    db.refresh(book)
    return {"status": "SUCCESS", "message": "Book updated successfully", "book_id": book.id}


@router.delete("/admin/{book_id}")
@router.delete("/api/books/admin/{book_id}")
def admin_delete_book(
    book_id: str,
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.get_current_admin),
):
    """Deletes a book record and cleans up associated R2 storage objects."""
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found.")

    # Remove files from R2 storage bucket
    for key in (book.file_url, book.cover_url):
        if _is_storage_key(key):
            try:
                s3.delete_object(Bucket=R2_BUCKET, Key=key)
            except Exception as r2_err:
                logger.warning("Failed to delete R2 object %s: %s", key, str(r2_err))

    db.delete(book)
    db.commit()
    return {"status": "SUCCESS", "message": "Book and storage objects deleted."}


@router.get("/admin/inventory")
@router.get("/api/books/admin/inventory")
def admin_book_inventory(
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.get_current_admin),
):
    """Retrieves full inventory including uploader info and status for admin tables."""
    results = (
        db.query(models.Book, models.User.email)
        .outerjoin(models.User, models.Book.user_id == models.User.id)
        .order_by(models.Book.created_at.desc())
        .all()
    )

    return [
        {
            "id": b.id,
            "title": b.title,
            "field": b.field or "Technology",
            "course": b.course or "General",
            "unit": b.unit or "General",
            "price": b.price,
            "description": getattr(b, "description", ""),
            "status": getattr(b, "status", "ACTIVE"),
            "admin_email": email or "System Admin",
            "created_at": b.created_at.isoformat() if b.created_at else None,
        }
        for b, email in results
    ]


@router.patch("/admin/{book_id}/toggle-status")
@router.patch("/api/books/admin/{book_id}/toggle-status")
def admin_toggle_book_status(
    book_id: str,
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.get_current_admin),
):
    """Toggles book visibility between ACTIVE and SUSPENDED."""
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found.")

    current_status = getattr(book, "status", "ACTIVE")
    new_status = "SUSPENDED" if current_status == "ACTIVE" else "ACTIVE"

    if hasattr(book, "status"):
        book.status = new_status
        db.commit()

    return {"status": "SUCCESS", "book_id": book.id, "new_status": new_status}


# =====================================================================
# 2. STORE CATALOG & PUBLIC / STUDENT ENDPOINTS
# =====================================================================

@router.get("/store")
@router.get("/")
def get_book_store_catalog(
    field: Optional[str] = Query(None, description="Filter by Academic/Professional Field"),
    course: Optional[str] = Query(None, description="Filter by Specific Course"),
    unit: Optional[str] = Query(None, description="Filter by Unit / Module"),
    search: Optional[str] = Query(None, description="Keyword search query"),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """Returns active books with hierarchical field & course filtering and ownership status."""
    query = db.query(models.Book).filter(models.Book.file_url.like("books/%"))

    # Exclude suspended books if status column exists
    if hasattr(models.Book, "status"):
        query = query.filter((models.Book.status == None) | (models.Book.status == "ACTIVE"))

    # Apply hierarchical filters
    if field and field.upper() != "ALL":
        query = query.filter(models.Book.field.ilike(f"%{field}%"))
    if course and course.upper() != "ALL":
        query = query.filter(models.Book.course.ilike(f"%{course}%"))
    if unit and unit.upper() != "ALL":
        query = query.filter(models.Book.unit.ilike(f"%{unit}%"))
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            (models.Book.title.ilike(search_pattern)) | 
            (models.Book.description.ilike(search_pattern)) |
            (models.Book.course.ilike(search_pattern))
        )

    books = query.order_by(models.Book.created_at.desc()).all()

    # Determine user's owned books
    owned_book_ids = {
        row.book_id
        for row in db.query(models.BookPurchase.book_id)
        .filter(
            models.BookPurchase.user_id == user.id,
            models.BookPurchase.status == "COMPLETED"
        )
        .all()
    }
    is_admin = bool(getattr(user, "is_admin", False))

    return [
        {
            "id": b.id,
            "title": b.title,
            "field": b.field or "Technology",
            "course": b.course or "General",
            "unit": b.unit or "General",
            "price": b.price,
            "description": b.description,
            "owned": is_admin or b.id in owned_book_ids,
            "cover_url": f"/api/books/{b.id}/cover" if _is_storage_key(b.cover_url) else None,
        }
        for b in books
    ]


@router.get("/{book_id}/cover")
def get_book_cover_image(book_id: str, db: Session = Depends(get_db)):
    """Streams book cover photo securely from R2 storage."""
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book or not _is_storage_key(book.cover_url):
        raise HTTPException(status_code=404, detail="Cover image not found.")

    try:
        r2_object = s3.get_object(Bucket=R2_BUCKET, Key=book.cover_url)
    except Exception:
        raise HTTPException(status_code=404, detail="Cover object missing in storage.")

    return Response(
        r2_object["Body"].read(),
        media_type=r2_object.get("ContentType") or "image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"}
    )


@router.get("/{book_id}/read-url")
def get_secure_book_read_url(
    book_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """Generates a time-limited presigned URL for reading purchased books."""
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book or not _is_storage_key(book.file_url):
        raise HTTPException(status_code=404, detail="Book document not found.")

    if not verify_book_access(db, user, book_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. You must purchase this book before reading."
        )

    try:
        presigned_url = s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": R2_BUCKET,
                "Key": book.file_url,
                "ResponseContentDisposition": "inline"
            },
            ExpiresIn=300  # URL valid for 5 minutes
        )
    except Exception as e:
        logger.exception("Failed to generate presigned read URL: %s", str(e))
        raise HTTPException(status_code=500, detail="Could not generate secure read link.")

    return {"status": "SUCCESS", "url": presigned_url}