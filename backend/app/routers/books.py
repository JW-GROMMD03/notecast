# routers/books.py  (complete replacement)
# R2 bucket stays PRIVATE. DB columns file_url / cover_url now hold R2 object KEYS, not URLs.
# Env: R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME,
#      R2_ENDPOINT_URL = https://<ACCOUNT_ID>.r2.cloudflarestorage.com   (no bucket name in it)
import logging
import os
import uuid
from typing import Optional

import boto3
from botocore.config import Config
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db

router = APIRouter(prefix="/books", tags=["Books"])
logger = logging.getLogger("notecast_books")

R2_BUCKET = os.getenv("R2_BUCKET_NAME", "notecast-books")
MIN_PRICE = 150

s3 = boto3.client(
    "s3",
    endpoint_url=os.getenv("R2_ENDPOINT_URL") or None,
    aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
    region_name="auto",
    config=Config(signature_version="s3v4"),
)

DOC_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
IMG_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def _ext(name: Optional[str]) -> str:
    return os.path.splitext(name or "")[1].lower()


def _is_key(v: Optional[str]) -> bool:
    return bool(v) and v.startswith("books/")


def has_access(db: Session, user, book_id: str) -> bool:
    if getattr(user, "is_admin", False):
        return True
    return (
        db.query(models.BookPurchase)
        .filter(models.BookPurchase.user_id == user.id, models.BookPurchase.book_id == book_id)
        .first()
        is not None
    )


def grant_book_access(db: Session, user_id: str, book_id: str) -> None:
    """Call this from the M-Pesa callback when a BOOK payment becomes COMPLETED."""
    exists = (
        db.query(models.BookPurchase)
        .filter(models.BookPurchase.user_id == user_id, models.BookPurchase.book_id == book_id)
        .first()
    )
    if not exists:
        db.add(models.BookPurchase(user_id=user_id, book_id=book_id))
        db.commit()


# ------------------------------------------------------------------ admin upload
@router.post("/admin/upload/")
def admin_upload_book(
    title: str = Form(...),
    course: str = Form(...),
    unit: str = Form("General"),
    price: float = Form(...),
    description: str = Form(""),
    book_file: UploadFile = File(...),
    cover_photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.get_current_admin),
):
    if price < MIN_PRICE:
        raise HTTPException(400, f"Minimum book price is {MIN_PRICE} KES.")

    doc_ext = _ext(book_file.filename)
    if doc_ext not in DOC_TYPES:
        raise HTTPException(400, "Invalid document format. Allowed: PDF, DOC, DOCX.")

    has_cover = bool(cover_photo and cover_photo.filename)
    cover_ext = _ext(cover_photo.filename) if has_cover else ""
    if has_cover and cover_ext not in IMG_TYPES:
        raise HTTPException(400, "Cover must be JPG, PNG or WEBP.")

    doc_key = f"books/documents/{uuid.uuid4().hex}{doc_ext}"
    cover_key = f"books/covers/{uuid.uuid4().hex}{cover_ext}" if has_cover else None

    try:
        s3.upload_fileobj(book_file.file, R2_BUCKET, doc_key, ExtraArgs={"ContentType": DOC_TYPES[doc_ext]})
        if cover_key:
            s3.upload_fileobj(cover_photo.file, R2_BUCKET, cover_key, ExtraArgs={"ContentType": IMG_TYPES[cover_ext]})
    except Exception as e:
        logger.exception("R2 upload failed")
        raise HTTPException(500, f"Storage upload failed: {e}")

    try:
        book = models.Book(
            title=title.strip(),
            course=course.strip(),
            unit=(unit or "General").strip(),
            price=price,
            file_url=doc_key,
            cover_url=cover_key,
            user_id=admin.id,
        )
        db.add(book)
        db.commit()
        db.refresh(book)
    except Exception as e:
        db.rollback()
        logger.exception("DB insert failed")
        raise HTTPException(500, f"Could not save book: {e}")

    return {"status": "SUCCESS", "book_id": book.id}


@router.delete("/admin/{book_id}")
def admin_delete_book(
    book_id: str,
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.get_current_admin),
):
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book:
        raise HTTPException(404, "Book not found")
    for key in (book.file_url, book.cover_url):
        if _is_key(key):
            try:
                s3.delete_object(Bucket=R2_BUCKET, Key=key)
            except Exception:
                logger.warning("Could not delete %s", key)
    db.delete(book)
    db.commit()
    return {"status": "DELETED"}


# ------------------------------------------------------------------ catalog
@router.get("/store")
def book_store(
    course: Optional[str] = Query(None),
    unit: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    q = db.query(models.Book).filter(models.Book.file_url.like("books/%"))  # hides legacy broken rows
    if course:
        q = q.filter(models.Book.course.ilike(f"%{course}%"))
    if unit:
        q = q.filter(models.Book.unit.ilike(f"%{unit}%"))
    books = q.order_by(models.Book.created_at.desc()).all()

    owned = {
        r.book_id
        for r in db.query(models.BookPurchase.book_id).filter(models.BookPurchase.user_id == user.id).all()
    }
    is_admin = bool(getattr(user, "is_admin", False))

    return [
        {
            "id": b.id,
            "title": b.title,
            "course": b.course or "General",
            "unit": b.unit or "General",
            "price": b.price,
            "owned": is_admin or b.id in owned,
            "cover_url": f"/api/books/{b.id}/cover" if _is_key(b.cover_url) else None,
        }
        for b in books
    ]


@router.get("/{book_id}/cover")
def book_cover(book_id: str, db: Session = Depends(get_db)):
    """Public on purpose (an <img> tag cannot send a login token). Covers are not secret."""
    b = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not b or not _is_key(b.cover_url):
        raise HTTPException(404)
    try:
        obj = s3.get_object(Bucket=R2_BUCKET, Key=b.cover_url)
    except Exception:
        raise HTTPException(404)
    return Response(
        obj["Body"].read(),
        media_type=obj.get("ContentType") or "image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/{book_id}/read-url")
def book_read_url(
    book_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    b = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not b or not _is_key(b.file_url):
        raise HTTPException(404, "Book file not found.")
    if not has_access(db, user, book_id):
        raise HTTPException(403, "Buy this book to read it.")
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": R2_BUCKET, "Key": b.file_url, "ResponseContentDisposition": "inline"},
        ExpiresIn=300,  # 5 minutes
    )
    return {"url": url}


# In routers/books.py

@router.get("/admin/inventory")
def admin_book_inventory(
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.get_current_admin),
):
    """Fetches all books in the store along with the admin who uploaded them."""
    results = db.query(models.Book, models.User.email).outerjoin(
        models.User, models.Book.user_id == models.User.id
    ).order_by(models.Book.created_at.desc()).all()
    
    return [
        {
            "id": b.id,
            "title": b.title,
            "course": b.course,
            "unit": b.unit,
            "price": b.price,
            "status": getattr(b, "status", "ACTIVE"), 
            "admin_email": email or "Unknown Admin",
            "created_at": b.created_at.isoformat() if b.created_at else None
        }
        for b, email in results
    ]

@router.patch("/admin/{book_id}/toggle-status")
def admin_toggle_book_status(
    book_id: str,
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.get_current_admin),
):
    """Suspends or activates a book in the store."""
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book:
        raise HTTPException(404, "Book not found")
    
    # If you don't have a status column in models.Book yet, this safely uses a fallback
    current_status = getattr(book, "status", "ACTIVE")
    new_status = "SUSPENDED" if current_status == "ACTIVE" else "ACTIVE"
    
    if hasattr(book, "status"):
        book.status = new_status
        db.commit()
        
    return {"status": "SUCCESS", "new_status": new_status}