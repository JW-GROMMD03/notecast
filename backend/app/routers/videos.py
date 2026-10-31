import io
import os
import tempfile
import requests
import datetime
import concurrent.futures
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DbSession
from sqlalchemy import func, text
from typing import List

from .. import models, schemas, auth
from ..database import get_db
from ..services import llm, storage as storage_service
from ..workers import pipeline
from ..config import settings

router = APIRouter(prefix="/videos", tags=["videos"])

# =========================================================================
# ADVANCED SUBSCRIPTION & ACCESS CONTROL MANAGER
# =========================================================================
class SubscriptionManager:
    @staticmethod
    def _get_package_limits(db: DbSession, tier_name: str):
        if not tier_name or tier_name.lower() == "free":
            return None
        
        normalized_tier = tier_name.upper().strip()
        
        # Built-in fallback limits matching all official NoteCast tiers
        defaults = {
            "QUICK": {"max_capture_minutes_per_day": 60, "max_docuvision_per_day": 5, "max_static_simulations_per_day": 5, "max_llm_simulations_per_day": 2},
            "QUICK_PASS": {"max_capture_minutes_per_day": 60, "max_docuvision_per_day": 5, "max_static_simulations_per_day": 5, "max_llm_simulations_per_day": 2},
            "LECTURE": {"max_capture_minutes_per_day": 120, "max_docuvision_per_day": 10, "max_static_simulations_per_day": 10, "max_llm_simulations_per_day": 5},
            "LECTURE_PASS": {"max_capture_minutes_per_day": 120, "max_docuvision_per_day": 10, "max_static_simulations_per_day": 10, "max_llm_simulations_per_day": 5},
            "MASTER": {"max_capture_minutes_per_day": 300, "max_docuvision_per_day": 20, "max_static_simulations_per_day": 20, "max_llm_simulations_per_day": 10},
            "MASTER_PASS": {"max_capture_minutes_per_day": 300, "max_docuvision_per_day": 20, "max_static_simulations_per_day": 20, "max_llm_simulations_per_day": 10},
            "WEEKLY": {"max_capture_minutes_per_day": 9999, "max_docuvision_per_day": 50, "max_static_simulations_per_day": 50, "max_llm_simulations_per_day": 20},
            "WEEKLY_SCHOLAR": {"max_capture_minutes_per_day": 9999, "max_docuvision_per_day": 50, "max_static_simulations_per_day": 50, "max_llm_simulations_per_day": 20},
            "MONTHLY": {"max_capture_minutes_per_day": 9999, "max_docuvision_per_day": 999, "max_static_simulations_per_day": 999, "max_llm_simulations_per_day": 999},
            "MONTHLY_PRO": {"max_capture_minutes_per_day": 9999, "max_docuvision_per_day": 999, "max_static_simulations_per_day": 999, "max_llm_simulations_per_day": 999},
        }

        try:
            row = db.execute(
                text("SELECT * FROM packages WHERE UPPER(plan_name) = :tier"), 
                {"tier": normalized_tier}
            ).fetchone()
            if row:
                return row._mapping if hasattr(row, '_mapping') else dict(row)
        except Exception:
            db.rollback()

        return defaults.get(normalized_tier, {"max_capture_minutes_per_day": 60, "max_docuvision_per_day": 5, "max_static_simulations_per_day": 5, "max_llm_simulations_per_day": 2})

    @staticmethod
    def log_usage(db: DbSession, user_id: str, action: str, resource_id: str = None):
        try:
            db.execute(
                text("""
                    INSERT INTO daily_usage (user_id, action, resource_id) 
                    VALUES (:uid, :act, :res)
                """),
                {"uid": user_id, "act": action, "res": resource_id}
            )
            db.commit()
        except Exception:
            db.rollback()

    @staticmethod
    def _get_active_tier(user: models.User, db: DbSession) -> str:
        tier = getattr(user, "subscription_tier", None)
        if not tier or tier.lower() == "free":
            try:
                sub_row = db.execute(
                    text("SELECT tier FROM user_subscriptions WHERE user_id = :uid AND status = 'active' AND expires_at > NOW() ORDER BY expires_at DESC LIMIT 1"),
                    {"uid": user.id}
                ).fetchone()
                if sub_row:
                    tier = sub_row[0]
            except Exception:
                db.rollback()
        return tier or "free"

    @staticmethod
    def can_download(user: models.User):
        pass

    @staticmethod
    def can_open_notes(user: models.User):
        pass

    @staticmethod
    def check_capture_minutes(user: models.User, db: DbSession, new_video_duration_sec: int):
        tier = SubscriptionManager._get_active_tier(user, db)
        if not tier or tier.lower() == "free":
            raise HTTPException(status_code=402, detail="Subscribe or activate a study pass to capture video notes.")
            
        limits = SubscriptionManager._get_package_limits(db, tier)
        if not limits:
            raise HTTPException(status_code=500, detail="Subscription package configuration missing.")
            
        max_minutes = limits.get('max_capture_minutes_per_day', 60)
        if max_minutes >= 9999: # Unlimited
            return
            
        today = datetime.datetime.utcnow().date()
        try:
            total_sec = db.execute(
                text("SELECT COALESCE(SUM(CAST(resource_id AS INTEGER)), 0) FROM daily_usage WHERE user_id = :uid AND action = 'capture_video' AND DATE(created_at) = :today"),
                {"uid": user.id, "today": today}
            ).scalar() or 0
        except Exception:
            db.rollback()
            total_sec = 0
        
        current_minutes = total_sec / 60.0
        new_minutes = (new_video_duration_sec or 0) / 60.0
        
        if current_minutes + new_minutes > max_minutes:
            raise HTTPException(
                status_code=429, 
                detail=f"Daily capture limit reached. Your plan allows {max_minutes} mins/day. You have used {int(current_minutes)} mins today."
            )

    @staticmethod
    def check_feature_daily_limit(user: models.User, db: DbSession, feature_name: str):
        tier = SubscriptionManager._get_active_tier(user, db)
        if not tier or tier.lower() == "free":
            raise HTTPException(status_code=402, detail=f"Subscribe to access {feature_name.title()}.")
            
        limits = SubscriptionManager._get_package_limits(db, tier)
        if not limits:
            raise HTTPException(status_code=500, detail="Subscription configuration missing in database.")
        
        max_limit = limits.get(f'max_{feature_name}_per_day', 0)
        if max_limit == 0:
            raise HTTPException(status_code=403, detail=f"Your current plan does not include {feature_name.title()} access.")
            
        today = datetime.datetime.utcnow().date()
        try:
            daily_usage = db.execute(
                text("SELECT COUNT(*) FROM daily_usage WHERE user_id = :uid AND action = :act AND DATE(created_at) = :today"),
                {"uid": user.id, "act": feature_name, "today": today}
            ).scalar() or 0
        except Exception:
            db.rollback()
            daily_usage = 0
        
        if daily_usage >= max_limit:
            raise HTTPException(status_code=429, detail=f"Daily limit of {max_limit} for {feature_name.title()} reached. Upgrade to continue today.")

    @staticmethod
    def check_simulation_limits(user: models.User, db: DbSession, is_llm: bool = False):
        tier = SubscriptionManager._get_active_tier(user, db)
        if not tier or tier.lower() == "free":
            raise HTTPException(status_code=402, detail="Subscribe to access Simulations.")
            
        limits = SubscriptionManager._get_package_limits(db, tier)
        if not limits:
            raise HTTPException(status_code=500, detail="Subscription package configuration missing.")

        action_type = "simulation_llm" if is_llm else "simulation_static"
        today = datetime.datetime.utcnow().date()
        try:
            daily_sims = db.execute(
                text("SELECT COUNT(*) FROM daily_usage WHERE user_id = :uid AND action = :act AND DATE(created_at) = :today"),
                {"uid": user.id, "act": action_type, "today": today}
            ).scalar() or 0
        except Exception:
            db.rollback()
            daily_sims = 0

        if is_llm:
            max_llm = limits.get('max_llm_simulations_per_day', 0)
            if max_llm == 0:
                raise HTTPException(status_code=403, detail="LLM Simulations require a higher premium subscription.")
            if daily_sims >= max_llm:
                raise HTTPException(status_code=429, detail=f"Limit reached: Max {max_llm} LLM simulations per day.")
        else:
            max_static = limits.get('max_static_simulations_per_day', 0)
            if max_static == 0:
                raise HTTPException(status_code=403, detail="Your package does not support static simulations.")
            if daily_sims >= max_static:
                raise HTTPException(status_code=429, detail=f"Limit reached: Max {max_static} static simulations per day.")

# =========================================================================
# ASYNC IMAGE DOWNLOADER
# =========================================================================
def get_real_image_path(storage_key):
    if not storage_key: return None
    s = str(storage_key).strip().replace("https://notecast-web.onrender.com/", "").replace("http://localhost:8000/", "")
    if s.startswith("api/"): s = s[4:]
    if s.startswith("/api/"): s = s[5:]

    download_url = None
    if s.startswith("http://") or s.startswith("https://"):
        download_url = s
    else:
        try:
            service_url = storage_service.local_url(s)
            if service_url and service_url.startswith("http"): download_url = service_url
        except Exception:
            pass

    if download_url:
        try:
            resp = requests.get(download_url, timeout=5)
            if resp.status_code == 200:
                ext = os.path.splitext(s)[1] or ".webp"
                fd, temp_path = tempfile.mkstemp(suffix=ext)
                with os.fdopen(fd, 'wb') as f:
                    f.write(resp.content)
                return temp_path
        except Exception:
            pass
    return None

def prefetch_images_concurrently(visuals):
    paths = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_visual = {
            executor.submit(get_real_image_path, getattr(v, 'storage_key', None) or getattr(v, 'image_path', None) or getattr(v, 'path', None)): v 
            for v in visuals
        }
        for future in concurrent.futures.as_completed(future_to_visual):
            v = future_to_visual[future]
            try:
                paths[v] = future.result()
            except Exception:
                paths[v] = None
    return paths

def get_pptx_safe_image_path(real_path):
    if not real_path or not os.path.exists(real_path): return None
    try:
        from PIL import Image
        img = Image.open(real_path)
        if img.mode in ("RGBA", "LA") or os.path.splitext(real_path)[1].lower() == '.webp':
            if img.mode == "P": img = img.convert("RGBA")
            elif img.mode not in ("RGB", "RGBA"): img = img.convert("RGB")
        converted_path = real_path + ".ppt_conv.png"
        if not os.path.exists(converted_path): img.save(converted_path, "PNG")
        return converted_path
    except Exception:
        return real_path

# =========================================================================
# ROUTES
# =========================================================================

@router.get("/verify-entitlement")
def verify_entitlement(action: str, resource_id: str = None, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    """Frontend-facing endpoint to check limits before rendering UI modals."""
    if action == "DOC_SUMMARIZATION":
        SubscriptionManager.check_feature_daily_limit(user, db, "docuvision")
        SubscriptionManager.log_usage(db, user.id, "docuvision", resource_id)
    elif action == "LAUNCH_STATIC_SIM":
        SubscriptionManager.check_simulation_limits(user, db, is_llm=False)
        SubscriptionManager.log_usage(db, user.id, "simulation_static", resource_id)
    return {"success": True}

@router.get("", response_model=List[schemas.VideoOut])
@router.get("/", response_model=List[schemas.VideoOut])
def list_videos(user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    return db.query(models.Video).filter(models.Video.user_id == user.id).order_by(models.Video.created_at.desc()).all()

@router.get("/{video_id}", response_model=schemas.VideoOut)
@router.get("/{video_id}/", response_model=schemas.VideoOut)
def get_video(video_id: str, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    SubscriptionManager.can_open_notes(user)
    video = db.query(models.Video).filter(models.Video.id == video_id, models.Video.user_id == user.id).first()
    if not video: raise HTTPException(status_code=404, detail="Video not found")
    return video

@router.post("", response_model=schemas.VideoOut)
@router.post("/", response_model=schemas.VideoOut)
def create_video(body: schemas.VideoCreateIn, request: Request, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    auth.verify_csrf(request)
    existing = db.query(models.Video).filter(models.Video.user_id == user.id, models.Video.youtube_id == body.youtube_id, models.Video.status != "completed").first()
    if existing: return existing
    video = models.Video(user_id=user.id, youtube_id=body.youtube_id, title=body.title, channel=body.channel, duration_sec=body.duration_sec, status="initializing")
    db.add(video)
    db.commit()
    db.refresh(video)
    return video

@router.post("/{video_id}/consent", response_model=dict)
@router.post("/{video_id}/consent/", response_model=dict)
def give_consent(video_id: str, body: schemas.ConsentIn, request: Request, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    auth.verify_csrf(request)
    video = db.query(models.Video).filter(models.Video.id == video_id, models.Video.user_id == user.id).first()
    if not video: raise HTTPException(status_code=404, detail="Video not found")
    db.add(models.ConsentLog(user_id=user.id, session_id=body.session_id, scope=body.scope))
    db.commit()
    return {"ok": True}

@router.post("/{video_id}/sessions", response_model=schemas.SessionOut)
@router.post("/{video_id}/sessions/", response_model=schemas.SessionOut)
def start_session(video_id: str, request: Request, seed_transcript: str = "", user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    auth.verify_csrf(request)
    video = db.query(models.Video).filter(models.Video.id == video_id, models.Video.user_id == user.id).first()
    if not video: raise HTTPException(status_code=404, detail="Video not found")
    if not db.query(models.ConsentLog).filter(models.ConsentLog.user_id == user.id).first():
        raise HTTPException(status_code=403, detail="Consent required before starting a session")
    
    # Verify Time limit & Log it
    SubscriptionManager.check_capture_minutes(user, db, video.duration_sec)
    SubscriptionManager.log_usage(db, user.id, "capture_video", str(video.duration_sec or 0))

    try:
        topic_model = llm.build_topic_model(video.title, video.channel, seed_transcript)
    except RuntimeError:
        topic_model = {"domain": "", "key_terms": [], "expected_concepts": []}
    
    session = models.Session(video_id=video.id, user_id=user.id, status="capturing", topic_model=topic_model)
    video.status = "capturing"
    db.add(session)
    db.commit()
    db.refresh(session)
    return session

@router.post("/{video_id}/finalize", response_model=dict)
@router.post("/{video_id}/finalize/", response_model=dict)
def finalize(video_id: str, request: Request, background_tasks: BackgroundTasks, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    auth.verify_csrf(request)
    video = db.query(models.Video).filter(models.Video.id == video_id, models.Video.user_id == user.id).first()
    if not video: raise HTTPException(status_code=404, detail="Video not found")
    for s in db.query(models.Session).filter(models.Session.video_id == video_id, models.Session.status == "capturing"): s.status = "ended"
    db.commit()
    background_tasks.add_task(pipeline.finalize_video, video_id)
    return {"ok": True, "status": "processing"}

@router.get("/{video_id}/captures", response_model=list)
@router.get("/{video_id}/captures/", response_model=list)
def get_video_captures(video_id: str, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    video = db.query(models.Video).filter(models.Video.id == video_id, models.Video.user_id == user.id).first()
    if not video: raise HTTPException(status_code=404, detail="Video not found")

    session_ids = [s.id for s in db.query(models.Session).filter(models.Session.video_id == video.id).all()]
    visuals = []
    if session_ids and hasattr(models, "VisualEvent"):
        visuals = db.query(models.VisualEvent).filter(models.VisualEvent.session_id.in_(session_ids)).order_by(models.VisualEvent.timestamp_ms).all()

    result = []
    for v in visuals:
        storage_key = getattr(v, 'storage_key', None) or getattr(v, 'image_path', None) or ''
        img_url = ""
        if storage_key:
            try: img_url = storage_service.local_url(storage_key)
            except Exception: img_url = storage_key if storage_key.startswith("http") else f"/{storage_key}"
        result.append({
            "id": getattr(v, 'id', ''), "type": getattr(v, 'type', 'Visual'),
            "description": getattr(v, 'description', '') or '', "ocr_text": getattr(v, 'ocr_text', '') or '',
            "timestamp_ms": getattr(v, 'timestamp_ms', 0), "image_url": img_url, "storage_key": storage_key
        })
    return result

@router.get("/{video_id}/download-pdf")
@router.get("/{video_id}/download-pdf/")
def download_pdf(video_id: str, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    SubscriptionManager.can_download(user)

    video = db.query(models.Video).filter(models.Video.id == video_id, models.Video.user_id == user.id).first()
    if not video: raise HTTPException(status_code=404, detail="Video not found")

    session_ids = [s.id for s in db.query(models.Session).filter(models.Session.video_id == video.id).all()]
    visuals = []
    try:
        if session_ids and hasattr(models, "VisualEvent"):
            visuals = db.query(models.VisualEvent).filter(models.VisualEvent.session_id.in_(session_ids)).order_by(models.VisualEvent.timestamp_ms).all()
    except Exception: pass

    if not visuals: raise HTTPException(status_code=404, detail="No captures found.")

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib import colors

        downloaded_images = prefetch_images_concurrently(visuals)

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
        story = []
        
        title_style = ParagraphStyle('MagDocTitle', fontName='Helvetica-Bold', fontSize=22, leading=26, textColor=colors.HexColor("#0f172a"), spaceAfter=6)
        subtitle_style = ParagraphStyle('MagDocSubtitle', fontName='Helvetica', fontSize=11, leading=14, textColor=colors.HexColor("#475569"), spaceAfter=15)
        h2_style = ParagraphStyle('MagHeading2', fontName='Helvetica-Bold', fontSize=14, leading=18, textColor=colors.HexColor("#1e293b"), spaceAfter=6)
        body_style = ParagraphStyle('MagBody', fontName='Helvetica', fontSize=10, leading=14, textColor=colors.HexColor("#334155"), spaceAfter=8)

        story.append(Paragraph(video.title or "NoteCast Visual Study Guide", title_style))
        story.append(Paragraph(f"<b>Channel:</b> {video.channel or 'Unknown'}  |  <b>Total Visual Captures:</b> {len(visuals)}", subtitle_style))
        story.append(Spacer(1, 10))

        for v in visuals:
            v_type = str(getattr(v, 'type', 'Visual')).upper()
            v_desc = str(getattr(v, 'description', '') or '')
            
            story.append(Paragraph(f"{v_type} Capture", h2_style))
            if v_desc: story.append(Paragraph(v_desc, body_style))
            
            real_path = downloaded_images.get(v)
            if real_path:
                try:
                    img = RLImage(real_path, width=512, height=288)
                    story.append(img)
                except Exception as img_err:
                    story.append(Paragraph(f"[Image error: {str(img_err)}]", body_style))
            else:
                story.append(Paragraph(f"[Image file not found]", body_style))
            story.append(Spacer(1, 18))

        doc.build(story)
        buffer.seek(0)
        safe_title = "".join(c for c in (video.title or "guide") if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename={safe_title}_Captures.pdf"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {str(e)}")

@router.get("/{video_id}/download-ppt")
@router.get("/{video_id}/download-ppt/")
def download_ppt(video_id: str, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    SubscriptionManager.can_download(user)
    
    video = db.query(models.Video).filter(models.Video.id == video_id, models.Video.user_id == user.id).first()
    if not video: raise HTTPException(status_code=404, detail="Video not found")

    session_ids = [s.id for s in db.query(models.Session).filter(models.Session.video_id == video.id).all()]
    visuals = []
    try:
        if session_ids and hasattr(models, "VisualEvent"):
            visuals = db.query(models.VisualEvent).filter(models.VisualEvent.session_id.in_(session_ids)).order_by(models.VisualEvent.timestamp_ms).all()
    except Exception: pass

    if not visuals: raise HTTPException(status_code=404, detail="No captures found.")

    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor

        downloaded_images = prefetch_images_concurrently(visuals)

        prs = Presentation()
        prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
        blank_layout = prs.slide_layouts[6]
        
        title_slide = prs.slides.add_slide(blank_layout)
        bg = title_slide.shapes.add_shape(1, 0, 0, prs.slide_width, prs.slide_height)
        bg.fill.solid()
        bg.fill.fore_color.rgb = RGBColor(15, 23, 42)
        bg.line.fill.background()

        tb = title_slide.shapes.add_textbox(Inches(1.0), Inches(2.2), Inches(11.333), Inches(3.0))
        tf = tb.text_frame
        tf.word_wrap = True
        
        p0 = tf.paragraphs[0]
        p0.text = video.title or "NoteCast Visual Study Guide"
        p0.font.size = Pt(40)
        p0.font.bold = True
        p0.font.color.rgb = RGBColor(255, 255, 255)
        p0.font.name = "Arial"
        
        p1 = tf.add_paragraph()
        p1.text = f"Channel: {video.channel or 'Unknown'}  |  Total Captures: {len(visuals)}"
        p1.font.size = Pt(18)
        p1.font.color.rgb = RGBColor(148, 163, 184)
        p1.font.name = "Arial"
        p1.space_before = Pt(20)

        for v in visuals:
            slide = prs.slides.add_slide(blank_layout)
            
            header_bg = slide.shapes.add_shape(1, 0, 0, prs.slide_width, Inches(1.0))
            header_bg.fill.solid()
            header_bg.fill.fore_color.rgb = RGBColor(30, 41, 59)
            header_bg.line.fill.background()

            v_type = str(getattr(v, 'type', 'Visual')).upper()
            t_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.15), Inches(11.5), Inches(0.7))
            t_tf = t_box.text_frame
            t_tf.word_wrap = True
            tp = t_tf.paragraphs[0]
            tp.text = f"{v_type} CAPTURE"
            tp.font.size = Pt(22)
            tp.font.bold = True
            tp.font.color.rgb = RGBColor(255, 255, 255)
            tp.font.name = "Arial"

            v_desc = str(getattr(v, 'description', '') or '')
            if v_desc:
                desc_box = slide.shapes.add_textbox(Inches(0.8), Inches(1.2), Inches(11.733), Inches(1.1))
                d_tf = desc_box.text_frame
                d_tf.word_wrap = True
                dp = d_tf.paragraphs[0]
                dp.text = v_desc
                dp.font.size = Pt(14)
                dp.font.color.rgb = RGBColor(71, 85, 105)
                dp.font.name = "Arial"
            
            real_path = downloaded_images.get(v)
            safe_ppt_path = get_pptx_safe_image_path(real_path) if real_path else None
            
            if safe_ppt_path:
                try:
                    img_top = Inches(2.4) if v_desc else Inches(1.3)
                    slide.shapes.add_picture(safe_ppt_path, Inches(0.8), img_top, height=Inches(4.7) if v_desc else Inches(5.8))
                except Exception as img_err:
                    err_box = slide.shapes.add_textbox(Inches(0.8), Inches(3.0), Inches(11.5), Inches(1.0))
                    etf = err_box.text_frame
                    ep = etf.paragraphs[0]
                    ep.text = f"[Could not load image: {str(img_err)}]"
                    ep.font.size = Pt(14)
                    ep.font.color.rgb = RGBColor(220, 38, 38)
            else:
                warn_box = slide.shapes.add_textbox(Inches(0.8), Inches(3.0), Inches(11.5), Inches(1.0))
                wt_tf = warn_box.text_frame
                wp = wt_tf.paragraphs[0]
                wp.text = "[Image file not found]"
                wp.font.size = Pt(14)
                wp.font.color.rgb = RGBColor(220, 38, 38)

        bio = io.BytesIO()
        prs.save(bio)
        bio.seek(0)
        safe_title = "".join(c for c in (video.title or "guide") if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        return StreamingResponse(bio, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation", headers={"Content-Disposition": f"attachment; filename={safe_title}_Captures.pptx"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate PPT: {str(e)}")