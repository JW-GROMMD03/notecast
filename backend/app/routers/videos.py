import io
import os
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DbSession
from typing import List

from .. import models, schemas, auth
from ..database import get_db
from ..services import llm
from ..workers import pipeline
from ..config import settings

router = APIRouter(tags=["videos"])


def get_real_image_path(storage_key):
    """Robustly resolve image file path across all possible storage configurations."""
    if not storage_key:
        return None
    s = str(storage_key).strip()
    candidates = []
    if os.path.isabs(s) and os.path.exists(s):
        return s
    candidates.append(s)
    candidates.append(os.path.join(os.getcwd(), s))
    if s.startswith("/"):
        candidates.append(s.lstrip("/"))
        candidates.append(os.path.join(os.getcwd(), s.lstrip("/")))
    if s.startswith("media/"):
        sub = s[len("media/"):]
        candidates.append(sub)
        candidates.append(os.path.join(os.getcwd(), sub))
        candidates.append(os.path.join(os.getcwd(), "media", sub))
    elif s.startswith("/media/"):
        sub = s[len("/media/"):]
        candidates.append(sub)
        candidates.append(os.path.join(os.getcwd(), sub))
        candidates.append(os.path.join(os.getcwd(), "media", sub))
    else:
        candidates.append(os.path.join("media", s))
        candidates.append(os.path.join(os.getcwd(), "media", s))
    try:
        if hasattr(settings, "storage_path") and settings.storage_path:
            sp = str(settings.storage_path)
            candidates.append(os.path.join(sp, s))
            candidates.append(os.path.join(sp, s.lstrip("/")))
            if s.startswith("media/"):
                candidates.append(os.path.join(sp, s[len("media/"):]))
            if s.startswith("/media/"):
                candidates.append(os.path.join(sp, s[len("/media/"):]))
    except Exception:
        pass
    for path in candidates:
        if path and os.path.exists(path) and os.path.isfile(path):
            return os.path.abspath(path)
    return None


def get_pptx_safe_image_path(real_path):
    """Converts WebP or unsupported image formats into PPT-compatible PNGs using Pillow."""
    if not real_path or not os.path.exists(real_path):
        return None
    try:
        from PIL import Image
        img = Image.open(real_path)
        if img.mode in ("RGBA", "LA") or os.path.splitext(real_path)[1].lower() == '.webp':
            if img.mode == "P":
                img = img.convert("RGBA")
            elif img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
        
        converted_path = real_path + ".ppt_conv.png"
        if not os.path.exists(converted_path):
            img.save(converted_path, "PNG")
        return converted_path
    except Exception:
        return real_path


@router.get("/videos", response_model=List[schemas.VideoOut])
def list_videos(user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    return (
        db.query(models.Video)
        .filter(models.Video.user_id == user.id)
        .order_by(models.Video.created_at.desc())
        .all()
    )


@router.get("/videos/{video_id}", response_model=schemas.VideoOut)
def get_video(video_id: str, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    video = db.query(models.Video).filter(models.Video.id == video_id, models.Video.user_id == user.id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


@router.post("/videos", response_model=schemas.VideoOut)
def create_video(body: schemas.VideoCreateIn, request: Request, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    """Step 0.3: extension sends scraped YouTube metadata; we create (or
    reuse) the video row. Actual capture starts once /sessions is called."""
    auth.verify_csrf(request)  # no-op for Bearer (extension) callers; enforced for cookie-mode web callers
    existing = (
        db.query(models.Video)
        .filter(models.Video.user_id == user.id, models.Video.youtube_id == body.youtube_id, models.Video.status != "completed")
        .first()
    )
    if existing:
        return existing
    video = models.Video(
        user_id=user.id,
        youtube_id=body.youtube_id,
        title=body.title,
        channel=body.channel,
        duration_sec=body.duration_sec,
        status="initializing",
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    return video


@router.post("/videos/{video_id}/consent")
def give_consent(video_id: str, body: schemas.ConsentIn, request: Request, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    """Step 0.2: DPIA consent gate — required before a session can start."""
    auth.verify_csrf(request)
    video = db.query(models.Video).filter(models.Video.id == video_id, models.Video.user_id == user.id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    db.add(models.ConsentLog(user_id=user.id, session_id=body.session_id, scope=body.scope))
    db.commit()
    return {"ok": True}


@router.post("/videos/{video_id}/sessions", response_model=schemas.SessionOut)
def start_session(video_id: str, request: Request, seed_transcript: str = "", user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    """Step 0.4-0.5: build the topic model and open a capture session.
    Requires a prior consent record for this video."""
    auth.verify_csrf(request)
    video = db.query(models.Video).filter(models.Video.id == video_id, models.Video.user_id == user.id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if not db.query(models.ConsentLog).filter(models.ConsentLog.user_id == user.id).first():
        raise HTTPException(status_code=403, detail="Consent required before starting a session")

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


@router.post("/videos/{video_id}/finalize")
def finalize(video_id: str, request: Request, background_tasks: BackgroundTasks, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    """Step 4.0: video playback ended — kick off reorganize/enrich/verify/export."""
    auth.verify_csrf(request)
    video = db.query(models.Video).filter(models.Video.id == video_id, models.Video.user_id == user.id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    for s in db.query(models.Session).filter(models.Session.video_id == video_id, models.Session.status == "capturing"):
        s.status = "ended"
    db.commit()
    background_tasks.add_task(pipeline.finalize_video, video_id)
    return {"ok": True, "status": "processing"}


@router.get("/videos/{video_id}/download-pdf")
def download_pdf(video_id: str, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    """Download all visual captures and slides as a magnificent, professionally formatted PDF document."""
    video = db.query(models.Video).filter(models.Video.id == video_id, models.Video.user_id == user.id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    session_ids = [s.id for s in db.query(models.Session).filter(models.Session.video_id == video.id).all()]
    visuals = []
    try:
        if session_ids and hasattr(models, "VisualEvent"):
            visuals = db.query(models.VisualEvent).filter(models.VisualEvent.session_id.in_(session_ids)).order_by(models.VisualEvent.timestamp_ms).all()
    except Exception:
        pass

    if not visuals:
        try:
            from sqlalchemy import text
            if not session_ids:
                session_rows = db.execute(text("SELECT id FROM sessions WHERE video_id = :vid"), {"vid": video.id}).fetchall()
                session_ids = [row[0] for row in session_rows]
            if session_ids:
                rows = db.execute(text("SELECT * FROM visual_events WHERE session_id IN :sids ORDER BY timestamp_ms"), {"sids": tuple(session_ids)}).fetchall()
                for row in rows:
                    mapping = row._mapping if hasattr(row, '_mapping') else dict(row)
                    class GenericVisual:
                        def __init__(self, d):
                            self.type = d.get('type') or d.get('visual_type') or 'Slide'
                            self.description = d.get('description') or d.get('title') or ''
                            self.storage_key = d.get('storage_key') or d.get('image_path') or d.get('path') or d.get('file_path') or ''
                    visuals.append(GenericVisual(mapping))
        except Exception:
            pass

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib import colors

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
        story = []

        title_style = ParagraphStyle(
            'MagDocTitle',
            fontName='Helvetica-Bold',
            fontSize=22,
            leading=26,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=6
        )
        subtitle_style = ParagraphStyle(
            'MagDocSubtitle',
            fontName='Helvetica',
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#475569"),
            spaceAfter=15
        )
        h2_style = ParagraphStyle(
            'MagHeading2',
            fontName='Helvetica-Bold',
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=6
        )
        body_style = ParagraphStyle(
            'MagBody',
            fontName='Helvetica',
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#334155"),
            spaceAfter=8
        )

        story.append(Paragraph(video.title or "NoteCast Visual Study Guide", title_style))
        story.append(Paragraph(f"<b>Channel:</b> {video.channel or 'Unknown'}  |  <b>Total Visual Captures:</b> {len(visuals)}", subtitle_style))
        story.append(Spacer(1, 10))

        for v in visuals:
            v_type = str(getattr(v, 'type', 'Visual')).upper()
            v_desc = str(getattr(v, 'description', '') or '')
            
            story.append(Paragraph(f"{v_type} Capture", h2_style))
            if v_desc:
                story.append(Paragraph(v_desc, body_style))
                story.append(Spacer(1, 4))

            storage_key = getattr(v, 'storage_key', None) or getattr(v, 'image_path', None) or getattr(v, 'path', None) or getattr(v, 'file_path', None)
            real_path = get_real_image_path(storage_key)

            if real_path:
                try:
                    img = RLImage(real_path, width=512, height=288)
                    story.append(img)
                except Exception as img_err:
                    story.append(Paragraph(f"[Image load error: {str(img_err)}]", body_style))
            else:
                story.append(Paragraph(f"[Image file not found on server for path: {storage_key}]", body_style))

            story.append(Spacer(1, 18))

        doc.build(story)
        buffer.seek(0)

        safe_title = "".join(c for c in (video.title or "guide") if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")

        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={safe_title}_Magnificent_Captures.pdf"}
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {str(e)}")


@router.get("/videos/{video_id}/download-ppt")
def download_ppt(video_id: str, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    """Download all visual captures and slides as a modern, professionally designed PowerPoint presentation (.pptx)."""
    video = db.query(models.Video).filter(models.Video.id == video_id, models.Video.user_id == user.id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    session_ids = [s.id for s in db.query(models.Session).filter(models.Session.video_id == video.id).all()]
    visuals = []
    try:
        if session_ids and hasattr(models, "VisualEvent"):
            visuals = db.query(models.VisualEvent).filter(models.VisualEvent.session_id.in_(session_ids)).order_by(models.VisualEvent.timestamp_ms).all()
    except Exception:
        pass

    if not visuals:
        try:
            from sqlalchemy import text
            if not session_ids:
                session_rows = db.execute(text("SELECT id FROM sessions WHERE video_id = :vid"), {"vid": video.id}).fetchall()
                session_ids = [row[0] for row in session_rows]
            if session_ids:
                rows = db.execute(text("SELECT * FROM visual_events WHERE session_id IN :sids ORDER BY timestamp_ms"), {"sids": tuple(session_ids)}).fetchall()
                for row in rows:
                    mapping = row._mapping if hasattr(row, '_mapping') else dict(row)
                    class GenericVisual:
                        def __init__(self, d):
                            self.type = d.get('type') or d.get('visual_type') or 'Slide'
                            self.description = d.get('description') or d.get('title') or ''
                            self.storage_key = d.get('storage_key') or d.get('image_path') or d.get('path') or d.get('file_path') or ''
                    visuals.append(GenericVisual(mapping))
        except Exception:
            pass

    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor

        prs = Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)

        blank_layout = prs.slide_layouts[6]
        
        # 1. Modern Title Slide
        title_slide = prs.slides.add_slide(blank_layout)
        bg = title_slide.shapes.add_shape(1, 0, 0, prs.slide_width, prs.slide_height)
        bg.fill.solid()
        bg.fill.fore_color.rgb = RGBColor(15, 23, 42) # Slate 900
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
        p1.font.color.rgb = RGBColor(148, 163, 184) # Slate 400
        p1.font.name = "Arial"
        p1.space_before = Pt(20)

        # 2. Content Slides for each visual capture
        for v in visuals:
            slide = prs.slides.add_slide(blank_layout)
            
            header_bg = slide.shapes.add_shape(1, 0, 0, prs.slide_width, Inches(1.0))
            header_bg.fill.solid()
            header_bg.fill.fore_color.rgb = RGBColor(30, 41, 59) # Slate 800
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
                dp.font.color.rgb = RGBColor(71, 85, 105) # Slate 600
                dp.font.name = "Arial"

            storage_key = getattr(v, 'storage_key', None) or getattr(v, 'image_path', None) or getattr(v, 'path', None) or getattr(v, 'file_path', None)
            real_path = get_real_image_path(storage_key)
            safe_ppt_path = get_pptx_safe_image_path(real_path)
            
            if safe_ppt_path:
                try:
                    img_top = Inches(2.4) if v_desc else Inches(1.3)
                    max_height = Inches(4.7) if v_desc else Inches(5.8)
                    slide.shapes.add_picture(safe_ppt_path, Inches(0.8), img_top, height=max_height)
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
                wp.text = f"[Image file not found on server for path: {storage_key}]"
                wp.font.size = Pt(14)
                wp.font.color.rgb = RGBColor(220, 38, 38)

        bio = io.BytesIO()
        prs.save(bio)
        bio.seek(0)

        safe_title = "".join(c for c in (video.title or "guide") if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        
        return StreamingResponse(
            bio,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={"Content-Disposition": f"attachment; filename={safe_title}_Captures.pptx"}
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to generate PowerPoint: {str(e)}")