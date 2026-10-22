"""
Object storage abstraction using Cloudflare R2 (S3-compatible).
"""
import base64
import uuid
import boto3
from botocore.config import Config
from ..config import settings

# Initialize the R2 client using S3 compatibility
s3 = boto3.client(
    "s3",
    endpoint_url=settings.R2_ENDPOINT_URL,
    aws_access_key_id=settings.R2_ACCESS_KEY_ID,
    aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
    region_name="auto",  # R2 requires this or us-east-1
    config=Config(signature_version="s3v4")
)

BUCKET = getattr(settings, "R2_BUCKET_NAME", "notecast-frames")


def save_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=data,
        ContentType=content_type
    )
    return key


def save_base64_image(prefix: str, b64_data: str, ext: str = "webp") -> str:
    if "," in b64_data:  # strip data: URL header if present
        b64_data = b64_data.split(",", 1)[1]
    raw = base64.b64decode(b64_data)
    key = f"frames/{prefix}/{uuid.uuid4().hex}.{ext}"
    
    content_type = f"image/{ext}"
    save_bytes(key, raw, content_type)
    return key


def read_bytes(key: str) -> bytes:
    response = s3.get_object(Bucket=BUCKET, Key=key)
    return response["Body"].read()


def local_url(key: str) -> str:
    """
    Generates a secure, temporary pre-signed URL to view the image directly from Cloudflare R2.
    This eliminates local 404 errors on Render and allows WeasyPrint/browsers to load frames cleanly.
    """
    if not key:
        return ""
    if key.startswith("http://") or key.startswith("https://"):
        return key
    
    url = s3.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": BUCKET, "Key": key},
        ExpiresIn=3600  # URL expires in 1 hour
    )
    return url