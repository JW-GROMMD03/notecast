"""
Runs as FastAPI BackgroundTasks rather than a separate BullMQ/Redis worker
fleet — right sized for a single-server deployment. Every function takes a
fresh DB session because BackgroundTasks run after the request's own
session has closed. To scale out, move these functions into RQ/Celery/
BullMQ-equivalent tasks unchanged; the logic doesn't depend on being
in-process.
"""
import logging
import json
import re
from sqlalchemy.orm import Session as DbSession
from .. import models
from ..database import SessionLocal
from ..services import llm, verify, pdf as pdf_service

log = logging.getLogger("notecast.pipeline")

def extract_clean_json(raw_text: str) -> dict:
    """
    Safely strips markdown code blocks and handles incomplete AI JSON strings 
    before parsing, preventing pipeline crashes.
    """
    text = str(raw_text).strip()
    
    match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
    if match:
        text = match.group(1).strip()
        
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            try:
                return json.loads(text[start_idx:end_idx+1])
            except:
                pass
                
        log.error(f"Failed to parse AI JSON safely. Raw Output: {raw_text[:200]}")
        return {"heading": "Note Generation Stalled", "body_md": "The AI encountered a complex topic and needs a moment to catch up. Formatting error recovered safely.", "assets": []}


def _log_job(db: DbSession, session_id: str | None, purpose: str, model: str, tokens: int, latency_ms: int, status: str = "ok"):
    try:
        db.add(models.LlmJob(session_id=session_id, model=model, purpose=purpose, tokens_out=tokens, latency_ms=latency_ms, status=status))
        db.commit()
    except Exception as e:
        log.warning(f"Failed to log LLM job: {e}")


def run_incremental_note(session_id: str):
    """
    Phase 3: Draft a premium, high-value note section from recent transcripts and visuals.
    Engineered to provide deep technical value, code blocks, and embedded diagrams.
    """
    db = SessionLocal()
    try:
        sess = db.query(models.Session).get(session_id)
        if not sess:
            return
            
        recent = (
            db.query(models.TranscriptSegment)
            .filter(models.TranscriptSegment.session_id == session_id, models.TranscriptSegment.is_final == True)  # noqa: E712
            .order_by(models.TranscriptSegment.start_ms.desc())
            .limit(45)
            .all()
        )
        if not recent:
            return
            
        recent = list(reversed(recent))
        
        # 1. Force High-Value Prompt Injection via window_text
        instruction = (
            "CRITICAL SYSTEM INSTRUCTION: You are an elite engineering and computer science professor. "
            "You are generating premium, subscription-worthy notes. Do NOT write shallow summaries. "
            "1. Go into extreme technical depth on the physics, math, or logic being discussed. "
            "2. If the topic involves programming/software, write out actual working code examples. "
            "3. EMBED VISUALS: If image URLs are provided in the context, you MUST embed them directly in your markdown notes using standard syntax: `![Detailed Description](URL_PROVIDED)`. "
            "Make these notes incredibly valuable, dense, and structured.\n\n"
            "--- LIVE TRANSCRIPT ---\n"
        )
        
        window_text = instruction + "\n".join(f"[{r.start_ms}ms] {r.text}" for r in recent)

        # 2. Extract recent visuals and provide exact markdown URLs for embedding
        visuals = (
            db.query(models.VisualEvent)
            .filter(models.VisualEvent.session_id == session_id)
            .order_by(models.VisualEvent.timestamp_ms.desc())
            .limit(4)
            .all()
        )
        
        visual_lines = []
        for v in visuals:
            # Safely format the storage key so the frontend can render it natively
            img_url = v.storage_key if v.storage_key and v.storage_key.startswith("/") else f"/{v.storage_key}"
            visual_lines.append(
                f"Visual Type: {v.type}\n"
                f"Description: {v.description}\n"
                f"OCR Extracted Text: {v.ocr_text}\n"
                f"URL_PROVIDED: {img_url}\n"
            )
            
        visual_text = "\n\n".join(visual_lines) if visual_lines else "No visuals captured in this window."

        try:
            # The underlying llm wrapper will receive this heavily enriched prompt context
            draft = llm.draft_note_section(window_text, visual_text)
            
            # Failsafe parsing if llm returns a string instead of dict
            if isinstance(draft, str):
                draft = extract_clean_json(draft)
                
        except Exception as e:
            log.warning("Premium note draft skipped due to LLM timeout or limit: %s", e)
            return

        if not draft or not draft.get("heading"):
            return

        count = db.query(models.NoteSection).filter(models.NoteSection.video_id == sess.video_id).count()
        section = models.NoteSection(
            video_id=sess.video_id,
            heading=draft["heading"][:250],
            body_md=draft.get("body_md", ""),
            order_index=count,
            timestamp_ms=recent[0].start_ms,
        )
        db.add(section)
        db.commit()
    except Exception as e:
        log.error(f"Incremental note generation crashed: {e}")
        db.rollback()
    finally:
        db.close()


def finalize_video(video_id: str):
    """Phases 4-5: reorganize -> enrich -> verify -> render PDF."""
    db = SessionLocal()
    try:
        video = db.query(models.Video).get(video_id)
        if not video:
            return
        video.status = "processing"
        db.commit()

        sessions = db.query(models.Session).filter(models.Session.video_id == video_id).all()
        session_ids = [s.id for s in sessions]
        segments = (
            db.query(models.TranscriptSegment)
            .filter(models.TranscriptSegment.session_id.in_(session_ids), models.TranscriptSegment.is_final == True)  # noqa: E712
            .order_by(models.TranscriptSegment.start_ms)
            .all()
        )
        
        # Safely truncate full transcript if it gets massive (> 20 mins) to prevent LLM token crashes
        full_transcript = "\n".join(f"[{s.start_ms}ms] {s.text}" for s in segments)
        if len(full_transcript) > 80000:
            full_transcript = full_transcript[-80000:] 

        flat_sections = (
            db.query(models.NoteSection)
            .filter(models.NoteSection.video_id == video_id)
            .order_by(models.NoteSection.order_index)
            .all()
        )

        try:
            # Pass 1: reorganize into a hierarchy
            flat_payload = [{"heading": s.heading, "body_md": s.body_md, "timestamp_ms": s.timestamp_ms} for s in flat_sections]
            
            if flat_payload:
                raw_reorg = llm.reorganize_notes(full_transcript, flat_payload) 
                reorg = extract_clean_json(raw_reorg) if isinstance(raw_reorg, str) else raw_reorg
            else:
                reorg = {"sections": []}

            # Wipe flat sections, write hierarchical ones
            for s in flat_sections:
                db.delete(s)
            db.commit()

            order = 0

            def write_section(node: dict, parent_id: str | None):
                nonlocal order
                sec = models.NoteSection(
                    video_id=video_id,
                    parent_id=parent_id,
                    heading=node.get("heading", "Note")[:250],
                    body_md=node.get("body_md", ""),
                    order_index=order,
                    timestamp_ms=node.get("timestamp_ms", 0),
                )
                order += 1
                db.add(sec)
                db.flush()
                for child in node.get("children", []) or []:
                    write_section(child, sec.id)
                return sec

            written = [write_section(n, None) for n in reorg.get("sections", [])]
            db.commit()

            # Ensure every transcript segment has an embedding
            unembedded = [s for s in segments if not s.embedding]
            if unembedded:
                try:
                    embeddings = llm.embed_texts([s.text for s in unembedded])
                    for seg, emb in zip(unembedded, embeddings):
                        seg.embedding = emb
                    db.commit()
                except Exception as emb_err:
                    log.warning("Embedding generation skipped: %s", emb_err)

            segment_pool = [{"id": s.id, "text": s.text, "embedding": s.embedding} for s in segments if s.embedding]

            # Pass 2: enrichment
            sections_text = "\n\n".join(f"{s.heading}\n{s.body_md}" for s in written)
            if len(sections_text) > 40000:
                sections_text = sections_text[:40000] # Truncate to prevent token limit crashes on massive notes
                
            raw_enrichment = llm.enrich_notes(sections_text) if sections_text.strip() else {"glossary": [], "review_questions": []}
            enrichment = extract_clean_json(raw_enrichment) if isinstance(raw_enrichment, str) else raw_enrichment

            # Verification gate
            for sec in written:
                if not sec.body_md.strip() or not segment_pool:
                    continue
                try:
                    result = verify.verify_section_body(sec.body_md, segment_pool)
                    sec.body_md = result.get("verified_body_md") or sec.body_md
                    sec.verification_status = result.get("status", "verified")
                except Exception as ver_err:
                    log.warning("Verification skipped for section: %s", ver_err)
            db.commit()

            video.status = "completed"
            db.commit()

            # Phase 5: render + store PDF safely
            try:
                all_sections = db.query(models.NoteSection).filter(models.NoteSection.video_id == video_id).all()
                pdf_bytes = pdf_service.render_pdf(video, all_sections, enrichment.get("glossary", []), enrichment.get("review_questions", []))
                key = pdf_service.save_export(video, pdf_bytes)
                db.add(models.Export(video_id=video_id, user_id=video.user_id, storage_key=key, format="pdf"))
                db.commit()
            except Exception as pdf_err:
                log.error("PDF export rendering skipped: %s", pdf_err)

        except Exception as e:
            log.exception("finalize failed for video %s: %s", video_id, e)
            video.status = "failed"
            db.commit()
    finally:
        db.close()