"""
routers/books.py - Full Production Book Store, Admin Management & R2 Storage Router
Note: R2 bucket remains PRIVATE for PDFs. DB columns file_url / cover_url store R2 object keys.
"""
import logging
import os
import uuid
import json
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
R2_PUBLIC_DOMAIN = os.getenv("R2_PUBLIC_DOMAIN", "").rstrip("/")
MIN_PRICE = 150  # Minimum book price in KES

# Initialize Redis (Speed Optimization)
try:
    import redis
    REDIS_AVAILABLE = True
    redis_client = redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        db=0,
        decode_responses=True
    )
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("Redis not installed. Catalog caching disabled. Run: pip install redis")

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


def _get_file_extension(filename: Optional[str]) -> str:
    if not filename:
        return ""
    return os.path.splitext(filename)[1].lower()


def _is_storage_key(value: Optional[str]) -> bool:
    return bool(value) and value.startswith("books/")


def _is_admin_user(user: models.User) -> bool:
    """Strictly evaluates admin status to prevent string 'false' or DB quirks from bypassing purchases."""
    if not user:
        return False
    val = getattr(user, "is_admin", False)
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return val == 1
    return str(val).strip().lower() in ["true", "1", "t", "y", "yes"]


def verify_book_access(db: Session, user: models.User, book_id: str) -> bool:
    """Returns True if the user is an admin or has an active purchase record for the book."""
    if _is_admin_user(user):
        return True
    
    try:
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
    except Exception as e:
        logger.error(f"Error evaluating book access: {e}")
        return False


def _invalidate_catalog_cache():
    if REDIS_AVAILABLE:
        try:
            for key in redis_client.scan_iter("catalog:*"):
                redis_client.delete(key)
        except Exception as e:
            logger.warning("Cache invalidation failed: %s", str(e))


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
    if price < MIN_PRICE:
        raise HTTPException(status_code=400, detail=f"Minimum book price is {MIN_PRICE} KES.")

    doc_ext = _get_file_extension(book_file.filename)
    if doc_ext not in ALLOWED_DOC_TYPES:
        raise HTTPException(status_code=400, detail="Invalid document format. Allowed types: PDF, DOC, DOCX.")

    has_cover = bool(cover_photo and cover_photo.filename)
    cover_ext = _get_file_extension(cover_photo.filename) if has_cover else ""
    if has_cover and cover_ext not in ALLOWED_IMG_TYPES:
        raise HTTPException(status_code=400, detail="Invalid cover image format. Allowed: JPG, PNG, WEBP.")

    doc_storage_key = f"books/documents/{uuid.uuid4().hex}{doc_ext}"
    cover_storage_key = f"books/covers/{uuid.uuid4().hex}{cover_ext}" if has_cover else None

    try:
        s3.upload_fileobj(
            book_file.file,
            R2_BUCKET,
            doc_storage_key,
            ExtraArgs={"ContentType": ALLOWED_DOC_TYPES[doc_ext]}
        )
        if cover_storage_key and cover_photo:
            s3.upload_fileobj(
                cover_photo.file,
                R2_BUCKET,
                cover_storage_key,
                ExtraArgs={"ContentType": ALLOWED_IMG_TYPES[cover_ext]}
            )
    except Exception as e:
        logger.exception("Cloudflare R2 upload error: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Storage upload failed: {str(e)}")

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
        _invalidate_catalog_cache()
    except Exception as db_err:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not persist book record in database.")

    return {"status": "SUCCESS", "message": "Book uploaded successfully", "book_id": new_book.id}


@router.put("/admin/{book_id}")
@router.put("/api/books/admin/{book_id}")
def admin_update_book(
    book_id: str,
    payload: BookUpdatePayload,
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.get_current_admin),
):
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found.")

    if payload.title is not None: book.title = payload.title.strip()
    if payload.field is not None: book.field = payload.field.strip()
    if payload.course is not None: book.course = payload.course.strip()
    if payload.unit is not None: book.unit = payload.unit.strip()
    if payload.description is not None: book.description = payload.description.strip()
    if payload.price is not None:
        if payload.price < MIN_PRICE:
            raise HTTPException(status_code=400, detail=f"Minimum price is {MIN_PRICE} KES.")
        book.price = payload.price

    db.commit()
    db.refresh(book)
    _invalidate_catalog_cache()
    return {"status": "SUCCESS", "message": "Book updated successfully", "book_id": book.id}


@router.delete("/admin/{book_id}")
@router.delete("/api/books/admin/{book_id}")
def admin_delete_book(
    book_id: str,
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.get_current_admin),
):
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found.")

    for key in (getattr(book, "file_url", None), getattr(book, "cover_url", None)):
        if _is_storage_key(key):
            try:
                s3.delete_object(Bucket=R2_BUCKET, Key=key)
            except Exception as r2_err:
                logger.warning("Failed to delete R2 object %s: %s", key, str(r2_err))

    db.delete(book)
    db.commit()
    _invalidate_catalog_cache()
    return {"status": "SUCCESS", "message": "Book and storage objects deleted."}


@router.get("/admin/inventory")
@router.get("/api/books/admin/inventory")
def admin_book_inventory(
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.get_current_admin),
):
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
            "field": getattr(b, "field", "Technology"),
            "course": getattr(b, "course", "General"),
            "unit": getattr(b, "unit", "General"),
            "price": b.price,
            "description": getattr(b, "description", ""),
            "status": getattr(b, "status", "ACTIVE"),
            "admin_email": email or "System Admin",
            "created_at": b.created_at.isoformat() if getattr(b, "created_at", None) else None,
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
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found.")

    current_status = getattr(book, "status", "ACTIVE")
    new_status = "SUSPENDED" if current_status == "ACTIVE" else "ACTIVE"

    if hasattr(book, "status"):
        book.status = new_status
        db.commit()
        _invalidate_catalog_cache()

    return {"status": "SUCCESS", "book_id": book.id, "new_status": new_status}


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
    from sqlalchemy import or_
    
    cache_key = f"catalog:{field or 'ALL'}:{course or 'ALL'}:{unit or 'ALL'}:{search or ''}"
    public_catalog = None
    
    if REDIS_AVAILABLE:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                public_catalog = json.loads(cached)
        except Exception as e:
            logger.warning("Redis read error: %s", str(e))
            
    if not public_catalog:
        try:
            query = db.query(models.Book)
            if hasattr(models.Book, "status"):
                query = query.filter((models.Book.status == None) | (models.Book.status == "ACTIVE"))

            if field and field.upper() != "ALL":
                if hasattr(models.Book, "field"):
                    query = query.filter(models.Book.field.ilike(f"%{field}%"))
            if course and course.upper() != "ALL":
                if hasattr(models.Book, "course"):
                    query = query.filter(
                        or_(
                            models.Book.course.ilike(f"%{course}%"),
                            models.Book.course_name.ilike(f"%{course}%") if hasattr(models.Book, "course_name") else False
                        )
                    )
            if unit and unit.upper() != "ALL":
                if hasattr(models.Book, "unit"):
                    query = query.filter(
                        or_(
                            models.Book.unit.ilike(f"%{unit}%"),
                            models.Book.unit_module.ilike(f"%{unit}%") if hasattr(models.Book, "unit_module") else False
                        )
                    )
            if search:
                search_pattern = f"%{search}%"
                search_filters = [models.Book.title.ilike(search_pattern)]
                if hasattr(models.Book, "description"):
                    search_filters.append(models.Book.description.ilike(search_pattern))
                if hasattr(models.Book, "course"):
                    search_filters.append(models.Book.course.ilike(search_pattern))
                query = query.filter(or_(*search_filters))

            books = query.order_by(models.Book.created_at.desc()).all() if hasattr(models.Book, "created_at") else query.all()
            
            public_catalog = []
            for b in books:
                cover_key = getattr(b, "cover_url", None) or getattr(b, "cover_photo_url", None) or getattr(b, "cover", None)
                
                if _is_storage_key(cover_key):
                    cover_url = f"{R2_PUBLIC_DOMAIN}/{cover_key}" if R2_PUBLIC_DOMAIN else f"/api/books/{b.id}/cover"
                else:
                    cover_url = None

                public_catalog.append({
                    "id": b.id,
                    "title": getattr(b, "title", "Untitled"),
                    "field": getattr(b, "field", None) or "Technology",
                    "course": getattr(b, "course", None) or getattr(b, "course_name", None) or "General",
                    "unit": getattr(b, "unit", None) or getattr(b, "unit_module", None) or "General",
                    "price": getattr(b, "price", 0.0),
                    "description": getattr(b, "description", None) or "",
                    "cover_url": cover_url,
                })
            
            if REDIS_AVAILABLE:
                try:
                    redis_client.setex(cache_key, 43200, json.dumps(public_catalog))
                except Exception as e:
                    logger.warning("Redis write error: %s", str(e))
                    
        except Exception as e:
            logger.exception("Error loading book store inventory from database: %s", str(e))
            raise HTTPException(status_code=500, detail="Failed to load book store inventory.")

    # "owned" means PURCHASED. Admin access is reported separately and never changes the paywall state.
    owned_book_ids = set()
    try:
        owned_book_ids = {
            row.book_id
            for row in db.query(models.BookPurchase.book_id)
            .filter(models.BookPurchase.user_id == user.id, models.BookPurchase.status == "COMPLETED")
            .all()
        }
    except Exception:
        logger.exception("Could not resolve purchases for user %s; treating all books as unowned", user.id)

    is_admin = _is_admin_user(user)
    return [
        {**b, "owned": b["id"] in owned_book_ids, "admin_preview": is_admin and b["id"] not in owned_book_ids}
        for b in public_catalog
    ]

@router.get("/my-library")
def get_my_library(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """Only books this user has actually paid for."""
    rows = (
        db.query(models.Book, models.BookPurchase.created_at)
        .join(models.BookPurchase, models.BookPurchase.book_id == models.Book.id)
        .filter(models.BookPurchase.user_id == user.id, models.BookPurchase.status == "COMPLETED")
        .order_by(models.BookPurchase.created_at.desc())
        .all()
    )
    out = []
    for b, purchased_at in rows:
        key = getattr(b, "cover_url", None) or getattr(b, "cover_photo_url", None) or getattr(b, "cover", None)
        out.append({
            "id": b.id,
            "title": b.title,
            "course": b.course or b.course_name or "General",
            "unit": b.unit or b.unit_module or "General",
            "price": b.price,
            "owned": True,
            "cover_url": (f"{R2_PUBLIC_DOMAIN}/{key}" if R2_PUBLIC_DOMAIN else f"/api/books/{b.id}/cover") if _is_storage_key(key) else None,
            "purchased_at": purchased_at.isoformat() if purchased_at else None,
        })
    return out


@router.get("/{book_id}/cover")
def get_book_cover_image(book_id: str, db: Session = Depends(get_db)):
    """Fallback route for cover photos if public R2 CDN is not configured."""
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    cover_key = getattr(book, "cover_url", None) or getattr(book, "cover_photo_url", None) or getattr(book, "cover", None)
    
    if not book or not _is_storage_key(cover_key):
        raise HTTPException(status_code=404, detail="Cover image not found.")

    try:
        r2_object = s3.get_object(Bucket=R2_BUCKET, Key=cover_key)
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
    file_key = getattr(book, "file_url", None) or getattr(book, "book_file_url", None) or getattr(book, "file", None)

    if not book or not _is_storage_key(file_key):
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
                "Key": file_key,
                "ResponseContentDisposition": "inline"
            },
            ExpiresIn=300  # URL valid for 5 minutes
        )
    except Exception as e:
        logger.exception("Failed to generate presigned read URL: %s", str(e))
        raise HTTPException(status_code=500, detail="Could not generate secure read link.")

    return {"status": "SUCCESS", "url": presigned_url}