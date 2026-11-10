import os
import boto3
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

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
    topic: str = Form(...),
    price: float = Form(...),
    description: str = Form(...),
    file: UploadFile = File(...),  # PDF or document file (.pdf, .docx, .doc)
    cover_file: UploadFile = File(
        None
    ),  # Optional custom cover image (.png, .jpg)
    # current_user: dict = Depends(verify_admin_user) # Uncomment when admin auth is active
):
  """Uploads a textbook document & optional cover image to Cloudflare R2 and records metadata in Supabase."""
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
  book_record = {
      "title": title,
      "course": course,
      "unit": unit,
      "topic": topic,
      "price": price,
      "description": description,
      "cover_url": cover_url,
      "document_url": document_url,
      "storage_key": doc_key,
  }

  # Example Supabase DB insertion (uncomment when database handle 'db' is active):
  # db.table("books").insert(book_record).execute()

  return {
      "status": "SUCCESS",
      "message": "Book and details uploaded successfully to Cloudflare R2",
      "book": book_record,
  }


@router.get("/books/")
async def get_all_books(
    course: str = None, unit: str = None, topic: str = None, sort: str = "latest"
):
  """Fetches filtered books from the database for the frontend library catalog."""
  # query = db.table("books").select("*")
  # if course: query = query.eq("course", course)
  # if unit: query = query.eq("unit", unit)
  # response = query.execute()
  # return response.data

  # Fallback mock payload matching R2 storage integration
  return [
      {
          "id": "b1",
          "title": "Distributed Systems Architecture",
          "course": "Software_Engineering",
          "unit": "Distributed_Systems",
          "topic": "Raft & Paxos",
          "popularity": 98,
          "date": "2026-09-01",
          "price": 150.0,
          "description": (
              "Comprehensive textbook exploring core consensus protocols,"
              " fault tolerance, and distributed log compaction algorithms."
          ),
          "cover_url": None,
          "document_url": "https://pub-xxx.r2.dev/sample.pdf",
          "storage_key": (
              "books/documents/Software_Engineering/Distributed_Systems/distributed.pdf"
          ),
      }
  ]