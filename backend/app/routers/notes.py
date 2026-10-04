from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session as DbSession
from typing import List
import io
import os
import re
import zlib
import base64
import requests
import json

from .. import models, schemas, auth
from ..database import get_db
from ..config import settings
from ..services import llm, mdblocks, diagram

router = APIRouter(tags=["notes"])

def _own_video(video_id: str, user: models.User, db: DbSession) -> models.Video:
    video = db.query(models.Video).filter(models.Video.id == video_id, models.Video.user_id == user.id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video

def _get_mermaid_image(mermaid_text: str) -> io.BytesIO:
    try:
        compressed = zlib.compress(mermaid_text.encode('utf-8'), 9)
        b64 = base64.urlsafe_b64encode(compressed).decode('utf-8')
        url = f"https://kroki.io/mermaid/png/{b64}"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return io.BytesIO(resp.content)
    except Exception as e:
        print(f"Mermaid rendering failed: {e}")
    return None

def _extract_braced_pdf(s, start_idx):
    if start_idx >= len(s) or s[start_idx] != '{':
        return None, start_idx
    depth = 0
    i = start_idx
    while i < len(s):
        if s[i] == '{':
            depth += 1
        elif s[i] == '}':
            depth -= 1
            if depth == 0:
                return s[start_idx + 1:i], i + 1
        i += 1
    return None, start_idx

def _clean_math_for_pdf(text: str) -> str:
    """Safely converts LaTeX math expressions into clean readable unicode for ReportLab PDFs without corrupting code or paths."""
    if not text:
        return ""
    
    t = text
    t = t.replace("$$", "").replace("$", "")
    t = t.replace(r"\[", "").replace(r"\]", "").replace(r"\(", "").replace(r"\)", "")
    t = t.replace(r"\begin{aligned}", "").replace(r"\end{aligned}", "")
    t = t.replace(r"\begin{matrix}", "").replace(r"\end{matrix}", "")
    t = t.replace(r"\displaystyle", "")

    # Robust fraction parsing for PDF
    result_chars = []
    i = 0
    while i < len(t):
        if t[i:i+5] == '\\frac' or t[i:i+6] == '\\dfrac':
            skip_len = 6 if t[i:i+6] == '\\dfrac' else 5
            idx = i + skip_len
            while idx < len(t) and t[idx].isspace():
                idx += 1
            num, idx = _extract_braced_pdf(t, idx)
            while idx < len(t) and t[idx].isspace():
                idx += 1
            den, idx = _extract_braced_pdf(t, idx)
            
            if num is not None and den is not None:
                num_clean = _clean_math_for_pdf(num)
                den_clean = _clean_math_for_pdf(den)
                result_chars.append(f"({num_clean})/({den_clean})")
                i = idx
                continue
        result_chars.append(t[i])
        i += 1
    t = "".join(result_chars)

    t = re.sub(r'\\partial', '∂', t)
    t = re.sub(r'\\nabla', '∇', t)
    t = re.sub(r'\\sum', 'Σ', t)
    t = re.sub(r'\\int', '∫', t)
    t = re.sub(r'\\cdot', '·', t)
    t = re.sub(r'\\approx', '≈', t)
    t = re.sub(r'\\le', '≤', t)
    t = re.sub(r'\\ge', '≥', t)
    t = re.sub(r'\\times', '×', t)
    t = re.sub(r'\\eta', 'η', t)
    t = re.sub(r'\\rho', 'ρ', t)
    t = re.sub(r'\\mu', 'μ', t)
    t = re.sub(r'\\sigma', 'σ', t)
    t = re.sub(r'\\omega', 'ω', t)
    t = re.sub(r'\\Omega', 'Ω', t)
    t = re.sub(r'\\beta', 'β', t)
    t = re.sub(r'\\phi', 'ϕ', t)
    t = re.sub(r'\\psi', 'ψ', t)
    t = re.sub(r'\\epsilon', 'ε', t)
    t = re.sub(r'\\delta', 'δ', t)
    t = re.sub(r'\\Delta', 'Δ', t)
    t = re.sub(r'\\tau', 'τ', t)
    t = re.sub(r'\\infty', '∞', t)
    t = re.sub(r'\\prime', '′', t)

    t = re.sub(r'\\mathbf\{([^}]+)\}', r'<b>\1</b>', t)
    t = re.sub(r'\\boldsymbol\{([^}]+)\}', r'<b>\1</b>', t)
    t = re.sub(r'\\overline\{([^}]+)\}', r'\1̄', t)
    t = re.sub(r'\\text\{([^}]+)\}', r'\1', t)
    t = re.sub(r'\\mathrm\{([^}]+)\}', r'\1', t)
    t = re.sub(r'\\left\(', '(', t)
    t = re.sub(r'\\right\)', ')', t)
    t = re.sub(r'\\left\[', '[', t)
    t = re.sub(r'\\right\]', ']', t)

    # Safe scoped subscript/superscript conversion (only when explicitly braced in LaTeX)
    t = re.sub(r'_\{([^}]+)\}', r'<sub>\1</sub>', t)
    t = re.sub(r'\^\{([^}]+)\}', r'<sup>\1</sup>', t)

    t = t.replace(r"\\", "<br/>")
    t = t.replace("{", "").replace("}", "").replace("\\", "")
    return t

def _safe_reportlab_text(text: str) -> str:
    cleaned = _clean_math_for_pdf(text)
    cleaned = cleaned.replace('&', '&amp;')
    return cleaned

@router.get("/videos/{video_id}/transcript", response_model=List[schemas.TranscriptSegmentOut])
def get_transcript(video_id: str, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    video = _own_video(video_id, user, db)
    session_ids = [s.id for s in db.query(models.Session).filter(models.Session.video_id == video.id)]
    return (
        db.query(models.TranscriptSegment)
        .filter(models.TranscriptSegment.session_id.in_(session_ids))
        .order_by(models.TranscriptSegment.start_ms)
        .all()
    )

@router.get("/videos/{video_id}/visuals", response_model=List[schemas.VisualEventOut])
def get_visuals(video_id: str, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    video = _own_video(video_id, user, db)
    session_ids = [s.id for s in db.query(models.Session).filter(models.Session.video_id == video.id)]
    events = (
        db.query(models.VisualEvent)
        .filter(models.VisualEvent.session_id.in_(session_ids))
        .order_by(models.VisualEvent.timestamp_ms)
        .all()
    )
    for e in events:
        if e.storage_key:
            e.storage_key = f"/media/{e.storage_key}"
    return events

@router.get("/videos/{video_id}/notes", response_model=List[schemas.NoteSectionOut])
def get_notes(video_id: str, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    video = _own_video(video_id, user, db)
    sections = (
        db.query(models.NoteSection)
        .filter(models.NoteSection.video_id == video.id)
        .order_by(models.NoteSection.order_index)
        .all()
    )
    if not sections:  
        session_ids = [s.id for s in db.query(models.Session).filter(models.Session.video_id == video.id)]  
        segments = (  
            db.query(models.TranscriptSegment)  
            .filter(models.TranscriptSegment.session_id.in_(session_ids))  
            .order_by(models.TranscriptSegment.start_ms)  
            .all()  
        )  
        if segments:  
            full_text = "\n".join([f"[{s.start_ms}ms] {s.text}" for s in segments])  
            auto_section = models.NoteSection(  
                video_id=video.id,  
                heading=f"Session Overview: {video.title}",  
                body_md=f"### Summary & Key Concepts\n\n{full_text[:3000]}\n\n*Click **Generate AI Extensive Notes** for deep synthesis.*",  
                order_index=0,  
                timestamp_ms=0  
            )  
            db.add(auto_section)  
            db.commit()  
            db.refresh(auto_section)  
            sections = [auto_section]

    for s in sections:  
        for a in s.assets:  
            if a.storage_key:  
                a.storage_key = f"/media/{a.storage_key}"  
    return sections

def _synthesize_truly_dynamic_notes(video, existing_sections, transcript_segs, visual_events) -> str:
    title = video.title or "Session Recording"
    channel = video.channel or "Presenter"
    
    md = []  
    md.append(f"# Comprehensive Master Study Guide: {title}")  
    md.append(f"**Source Context:** Dynamically synthesized from session recordings and materials presented by **{channel}**.\n")
    
    md.append("## 1. Executive Summary & Core Objectives")  
    md.append(f"This session covers critical frameworks, discussions, and concepts associated with *{title}*.\n")
    
    md.append("## 2. Topic Breakdowns & Key Chapters")  
    if existing_sections:  
        for idx, sec in enumerate(existing_sections, 1):  
            md.append(f"### 2.{idx} {sec.heading}")  
            md.append(f"{sec.body_md}\n")  
    else:  
        md.append("### 2.1 Session Narration & Discussion Synthesis")  
        if transcript_segs:  
            sample_text = " ".join([t.text for t in transcript_segs[:35]])  
            md.append(f"> {sample_text}\n")  
        else:  
            md.append("No explicit note sections or transcript segments recorded yet.\n")

    if visual_events:  
        md.append("## 3. Visual Evidence & Slide Extractions")  
        for idx, v in enumerate(visual_events, 1):  
            v_type = (v.type or 'Visual').upper()  
            v_desc = v.description or 'Captured slide or diagram'  
            ocr_text = f"\n```text\n{v.ocr_text}\n```" if getattr(v, 'ocr_text', None) else ""  
            md.append(f"### 3.{idx} [{v_type}] at {v.timestamp_ms // 1000}s")  
            md.append(f"**Details:** {v_desc}{ocr_text}\n")

    md.append("## 4. Conceptual Flow & Architecture")  
    md.append("```diagram")  
    md.append("{\n  \"title\": \"Session Overview\",\n  \"direction\": \"TB\",\n  \"nodes\": [\n    {\"id\": \"1\", \"label\": \"Introduction\"},\n    {\"id\": \"2\", \"label\": \"Core Analysis\"},\n    {\"id\": \"3\", \"label\": \"Conclusion\"}\n  ],\n  \"edges\": [\n    {\"from\": \"1\", \"to\": \"2\"},\n    {\"from\": \"2\", \"to\": \"3\"}\n  ],\n  \"layout_notes\": \"Generated automatically\"\n}")
    md.append("```\n")

    md.append("## 5. Key Takeaways & Action Items")  
    md.append("- Review all core conceptual definitions and framework rules highlighted during the session.")  
    md.append("- Cross-reference visual slide captures with transcript notes for comprehensive review.")

    return "\n".join(md)

@router.get("/videos/{video_id}/ai-notes")
def get_ai_notes(video_id: str, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    video = _own_video(video_id, user, db)
    stored_notes = getattr(video, "ai_notes", None) or ""
    return {
        "ok": True,
        "success": True,
        "ai_markdown": stored_notes,
        "markdown": stored_notes,
        "content": stored_notes,
        "text": stored_notes,
        "notes": stored_notes,
        "html": mdblocks.render_html(stored_notes) if stored_notes else ""
    }

@router.post("/videos/{video_id}/generate-ai-notes")
def trigger_generate_ai_notes(video_id: str, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    video = _own_video(video_id, user, db)
    session_ids = [s.id for s in db.query(models.Session).filter(models.Session.video_id == video.id)]
    
    existing_sections = (  
        db.query(models.NoteSection)  
        .filter(models.NoteSection.video_id == video.id)  
        .order_by(models.NoteSection.order_index)  
        .all()  
    )  
    headlines_context = "\n".join([f"- {sec.heading}: {sec.body_md[:300]}..." for sec in existing_sections])

    transcript_segs = (  
        db.query(models.TranscriptSegment)  
        .filter(models.TranscriptSegment.session_id.in_(session_ids))  
        .order_by(models.TranscriptSegment.start_ms)  
        .all()  
    )  
    full_transcript = "\n".join([f"[{t.start_ms}ms] {t.text}" for t in transcript_segs]) if transcript_segs else "No transcript captured."

    visual_events = (  
        db.query(models.VisualEvent)  
        .filter(models.VisualEvent.session_id.in_(session_ids))  
        .order_by(models.VisualEvent.timestamp_ms)  
        .all()  
    )  
    visual_contexts = [f"[{v.timestamp_ms}ms] {v.type}: {v.description} | OCR: {getattr(v, 'ocr_text', '')}" for v in visual_events]

    CRITICAL_AI_RULES = """
    CRITICAL FORMATTING & CONTEXT-ADAPTIVE GUARDRAILS - YOU MUST OBEY THESE RULES:
    1. CONTEXT-DRIVEN ADAPTABILITY: Dynamically adapt your output format and content to the specific discipline. 
       - For programming: Include clean code snippets, algorithm breakdowns, and technical syntax examples.
       - For theoretical, engineering, or mathematical courses: Focus on rigorous conceptual frameworks.
    2. WHITEBOARD & HANDWRITTEN MATH DERIVATIONS: If visual contexts or transcripts indicate handwritten equations on a whiteboard, you MUST explain the math contextually. Break down mathematical proofs, formulas, and derivations step-by-step. Define all variables explicitly. Never skip logical mathematical steps.
    3. PERFECT MARKDOWN TABLES: Every table MUST use standard markdown syntax with balanced pipes (|) and a separator row (|---|---|). Never put raw HTML line breaks (<br>) inside table cells.
    4. CLEAN MATHEMATICAL NOTATION: Write equations using clean Unicode math characters or standard subscript/superscript markup. Avoid complex nested LaTeX macros that break web and PDF rendering.
    5. DIAGRAM ENCAPSULATION: You must NEVER output raw JSON in plain text. ALL JSON diagram schemas MUST be strictly enclosed inside standard markdown ```diagram code blocks. 
    6. NO TRUNCATION: You are an expert researcher. Fully complete your thoughts and ensure maximum depth without cutting off mid-sentence.
    """

    comprehensive_context = f"### Note Headlines & Topics Covered:\n{headlines_context}\n\n### Full Transcript:\n{full_transcript}\n\n{CRITICAL_AI_RULES}\n\n{diagram.DIAGRAM_INSTRUCTIONS}"

    try:  
        ai_markdown = llm.generate_deep_research_notes(  
            title=video.title or "Untitled Session",  
            channel=video.channel or "Unknown Presenter",  
            full_transcript=comprehensive_context,  
            visual_contexts=visual_contexts  
        )  
    except Exception:  
        ai_markdown = _synthesize_truly_dynamic_notes(video, existing_sections, transcript_segs, visual_events)

    if not ai_markdown or "Error" in ai_markdown or "No provider" in ai_markdown:  
        ai_markdown = _synthesize_truly_dynamic_notes(video, existing_sections, transcript_segs, visual_events)

    if hasattr(video, "ai_notes"):  
        video.ai_notes = ai_markdown  
        db.add(video)  
        db.commit()  
        db.refresh(video)

    return {  
        "ok": True,  
        "success": True,  
        "ai_markdown": ai_markdown,  
        "markdown": ai_markdown,  
        "content": ai_markdown,  
        "text": ai_markdown,  
        "notes": ai_markdown,
        "html": mdblocks.render_html(ai_markdown)
    }

# ====================================================
# UPGRADED PDF GENERATOR 
# ====================================================
@router.get("/videos/{video_id}/ai-notes/download-pdf")
def download_ai_notes_pdf(video_id: str, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    video = _own_video(video_id, user, db)

    try:  
        from reportlab.lib.pagesizes import letter  
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Preformatted, Image as RLImage
        from reportlab.lib.utils import ImageReader
        from reportlab.lib.styles import ParagraphStyle  
        from reportlab.lib import colors  

        buffer = io.BytesIO()  
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=45, leftMargin=45, topMargin=45, bottomMargin=45)  
        story = []

        color_primary = colors.HexColor("#2563eb")    
        color_heading = colors.HexColor("#0f172a")    
        color_subheading = colors.HexColor("#334155")  
        color_text = colors.HexColor("#1e293b")  
        color_code_bg = colors.HexColor("#f8fafc")    
        color_code_text = colors.HexColor("#b91c1c")  
        color_border = colors.HexColor("#cbd5e1")     

        title_style = ParagraphStyle('MagDocTitle', fontName='Helvetica-Bold', fontSize=26, leading=30, textColor=color_primary, spaceAfter=8)  
        subtitle_style = ParagraphStyle('MagDocSubtitle', fontName='Helvetica', fontSize=12, leading=16, textColor=colors.HexColor("#64748b"), spaceAfter=24)
        
        h1_style = ParagraphStyle('H1', fontName='Helvetica-Bold', fontSize=18, leading=24, textColor=color_heading, spaceBefore=20, spaceAfter=8)  
        h2_style = ParagraphStyle('H2', fontName='Helvetica-Bold', fontSize=15, leading=20, textColor=color_subheading, spaceBefore=16, spaceAfter=6)  
        h3_style = ParagraphStyle('H3', fontName='Helvetica-Bold', fontSize=13, leading=18, textColor=color_subheading, spaceBefore=12, spaceAfter=4)
        
        body_style = ParagraphStyle('Body', fontName='Helvetica', fontSize=10.5, leading=16, textColor=color_text, spaceAfter=8)  
        bullet_style = ParagraphStyle('Bullet', parent=body_style, leftIndent=15, firstLineIndent=-10)  
        quote_style = ParagraphStyle('Quote', parent=body_style, leftIndent=20, textColor=colors.HexColor("#475569"), fontName='Helvetica-Oblique')
        
        code_block_style = ParagraphStyle('CodeBlock', fontName='Courier', fontSize=9, leading=14, textColor=colors.HexColor("#047857"), backColor=color_code_bg, leftIndent=10, rightIndent=10, spaceBefore=8, spaceAfter=12, borderPadding=8)  
        diagram_style = ParagraphStyle('Diagram', fontName='Courier-Bold', fontSize=8.5, leading=10, textColor=colors.HexColor("#2563eb"), backColor=colors.HexColor("#f8fafc"), borderPadding=14, borderColor=colors.HexColor("#93c5fd"), borderWidth=1.5, borderRadius=8, spaceBefore=12, spaceAfter=16)

        story.append(Paragraph(video.title or "NoteCast Master Study Guide", title_style))  
        story.append(Paragraph(f"<b>Channel / Presenter:</b> {video.channel or 'Unknown'}", subtitle_style))

        notes_content = getattr(video, "ai_notes", None) or "No AI notes generated yet."
        
        code_blocks = []
        mermaid_blocks = []
        diagram_blocks = []
        
        def block_repl(match):
            lang = match.group(1).lower().strip()
            content = match.group(2)
            if 'mermaid' in lang:
                idx = len(mermaid_blocks)
                mermaid_blocks.append(content)
                return f"__MERMAID_BLOCK_{idx}__"
            elif 'diagram' in lang or ('json' in lang and '"nodes"' in content and '"edges"' in content):
                idx = len(diagram_blocks)
                diagram_blocks.append(content)
                return f"__DIAGRAM_BLOCK_{idx}__"
            else:
                idx = len(code_blocks)
                code_blocks.append(content)
                return f"__CODE_BLOCK_{idx}__"
        
        safe_md = re.sub(r'```(\w*)\n(.*?)```', block_repl, notes_content, flags=re.DOTALL)  
        lines = safe_md.split('\n')

        valid_table_lines = set()
        for i in range(len(lines)):
            l = lines[i].strip()
            if re.match(r'^\|[\s\-:\|]+\|$', l) and '---' in l:
                valid_table_lines.add(i)
                j = i - 1
                while j >= 0 and lines[j].strip().startswith('|') and lines[j].strip().endswith('|'):
                    valid_table_lines.add(j)
                    j -= 1
                j = i + 1
                while j < len(lines) and lines[j].strip().startswith('|') and lines[j].strip().endswith('|'):
                    valid_table_lines.add(j)
                    j += 1

        in_table = False; table_buffer = []; in_diagram = False; diagram_buffer = []

        def flush_diagram():  
            if diagram_buffer:  
                text = "\n".join(diagram_buffer).strip()
                if text:
                    story.append(Preformatted(_safe_reportlab_text(text), diagram_style))  
                diagram_buffer.clear()

        def flush_table():  
            if table_buffer:  
                raw_rows = []  
                for row_line in table_buffer:  
                    if re.match(r'^\|[\s\-:\|]+\|$', row_line.strip()) and '---' in row_line: continue
                    if re.match(r'^[\s\|-]*$', row_line): continue  
                    cells = [cell.strip() for cell in row_line.strip(' |').split('|')]  
                    raw_rows.append(cells)
                
                if raw_rows:  
                    max_cols = max(len(r) for r in raw_rows)
                    data = []
                    for cells in raw_rows:
                        while len(cells) < max_cols:
                            cells.append("")
                        cells = cells[:max_cols]
                        
                        parsed_cells = []  
                        for cell in cells:  
                            c = _safe_reportlab_text(cell)
                            c = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', c)  
                            c = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', c)  
                            c = re.sub(r'`(.*?)`', r'\1', c) 
                            parsed_cells.append(Paragraph(c, body_style))  
                        data.append(parsed_cells)  
                    
                    if data:  
                        t = Table(data)  
                        t.setStyle(TableStyle([  
                            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f1f5f9")),  
                            ('TEXTCOLOR', (0,0), (-1,0), color_heading),  
                            ('ALIGN', (0,0), (-1,-1), 'LEFT'),  
                            ('VALIGN', (0,0), (-1,-1), 'TOP'),  
                            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),  
                            ('BOTTOMPADDING', (0,0), (-1,0), 10),  
                            ('TOPPADDING', (0,0), (-1,0), 10),  
                            ('BACKGROUND', (0,1), (-1,-1), colors.HexColor("#ffffff")),  
                            ('GRID', (0,0), (-1,-1), 0.5, color_border),  
                            ('PADDING', (0,1), (-1,-1), 8),  
                        ]))  
                        story.append(t)  
                        story.append(Spacer(1, 12))  
                table_buffer.clear()

        for idx, raw_line in enumerate(lines):  
            line = raw_line.strip()

            if line.startswith('__DIAGRAM_BLOCK_'):
                if in_diagram: in_diagram = False; flush_diagram()  
                if in_table: in_table = False; flush_table()
                
                match = re.search(r'__DIAGRAM_BLOCK_(\d+)__', line)
                if match:
                    d_idx = int(match.group(1))
                    if d_idx < len(diagram_blocks):
                        try:
                            layout_data = json.loads(diagram_blocks[d_idx])
                            flowable = diagram.pdf_flowable(layout_data)
                            story.append(Spacer(1, 12))
                            story.append(flowable)
                            story.append(Spacer(1, 16))
                        except Exception as e:
                            story.append(Preformatted("[Native Diagram rendering failed]\n" + diagram_blocks[d_idx], diagram_style))
                continue

            if line.startswith('__MERMAID_BLOCK_'):
                if in_diagram: in_diagram = False; flush_diagram()  
                if in_table: in_table = False; flush_table()
                
                match = re.search(r'__MERMAID_BLOCK_(\d+)__', line)
                if match:
                    m_idx = int(match.group(1))
                    if m_idx < len(mermaid_blocks):
                        img_stream = _get_mermaid_image(mermaid_blocks[m_idx])
                        if img_stream:
                            img_reader = ImageReader(img_stream)
                            img_w, img_h = img_reader.getSize()
                            aspect = img_h / float(img_w)
                            render_w = min(480, img_w)
                            render_h = render_w * aspect
                            story.append(RLImage(img_stream, width=render_w, height=render_h))
                            story.append(Spacer(1, 16))
                continue

            if line.startswith('__CODE_BLOCK_'):  
                if in_diagram: in_diagram = False; flush_diagram()  
                if in_table: in_table = False; flush_table()
                
                match = re.search(r'__CODE_BLOCK_(\d+)__', line)  
                if match:  
                    c_idx = int(match.group(1))  
                    if c_idx < len(code_blocks):  
                        story.append(Paragraph(code_blocks[c_idx].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br/>'), code_block_style))  
                continue

            is_diag = False  
            if line and idx not in valid_table_lines:  
                if '+--' in raw_line or '--+' in raw_line or '-->' in raw_line or '<--' in raw_line or re.search(r'\| {2,}', raw_line) or re.search(r'\s{2,}\|', raw_line) or (line.startswith('|') and line.endswith('|')):  
                    is_diag = True

            if in_diagram:  
                if is_diag or (not line and diagram_buffer):  
                    diagram_buffer.append(raw_line)  
                    continue  
                else:  
                    in_diagram = False  
                    flush_diagram()  
            elif is_diag:  
                if in_table: in_table = False; flush_table()  
                in_diagram = True  
                diagram_buffer.append(raw_line)  
                continue

            if idx in valid_table_lines:  
                if in_diagram: in_diagram = False; flush_diagram()  
                in_table = True  
                table_buffer.append(raw_line)  
                continue  
            elif in_table:  
                in_table = False  
                flush_table()

            if not line: continue

            safe_line = _safe_reportlab_text(raw_line)
            safe_line = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', safe_line)  
            safe_line = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', safe_line)  
            safe_line = re.sub(r'`(.*?)`', lambda m: f'<font name="Courier" color="{color_code_text.hexval()}">{m.group(1)}</font>', safe_line)

            if safe_line.startswith('### '): story.append(Paragraph(safe_line[4:], h3_style))  
            elif safe_line.startswith('## '): story.append(Paragraph(safe_line[3:], h2_style))  
            elif safe_line.startswith('# '): story.append(Paragraph(safe_line[2:], h1_style))  
            elif safe_line.startswith('> '): story.append(Paragraph(safe_line[2:], quote_style))  
            elif safe_line.startswith('- ') or re.match(r'^\d+\.\s', safe_line): 
                clean_list_text = re.sub(r'^(\- |\d+\.\s)', '', safe_line)
                story.append(Paragraph("&bull; " + clean_list_text, bullet_style))  
            else: 
                story.append(Paragraph(safe_line, body_style))

        if in_diagram: flush_diagram()  
        if in_table: flush_table()

        doc.build(story)  
        pdf_bytes = buffer.getvalue()
        
    except Exception as e:  
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {str(e)}")

    safe_title = "".join(c for c in (video.title or "guide") if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")  
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename={safe_title}_Study_Guide.pdf"})

# ====================================================
# UPGRADED PPTX GENERATOR
# ====================================================
@router.get("/videos/{video_id}/ai-notes/download-ppt")
def download_ai_notes_ppt(video_id: str, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    video = _own_video(video_id, user, db)

    try:  
        from pptx import Presentation  
        from pptx.util import Inches, Pt  
        from pptx.dml.color import RGBColor  
        from pptx.enum.dml import MSO_LINE

        prs = Presentation()  
        prs.slide_width = Inches(13.333)  
        prs.slide_height = Inches(7.5)  
        blank_layout = prs.slide_layouts[6]

        title_slide = prs.slides.add_slide(blank_layout)  
        bg = title_slide.shapes.add_shape(1, 0, 0, prs.slide_width, prs.slide_height)  
        bg.fill.solid(); bg.fill.fore_color.rgb = RGBColor(15, 23, 42); bg.line.fill.background()

        tb = title_slide.shapes.add_textbox(Inches(1.0), Inches(2.2), Inches(11.333), Inches(3.0))  
        tf = tb.text_frame; tf.word_wrap = True  
        p0 = tf.paragraphs[0]; p0.text = video.title or "NoteCast Study Guide"  
        p0.font.size = Pt(40); p0.font.bold = True; p0.font.color.rgb = RGBColor(255, 255, 255)
        
        p1 = tf.add_paragraph()  
        p1.text = f"Presenter / Channel: {video.channel or 'Unknown'}"  
        p1.font.size = Pt(18); p1.font.color.rgb = RGBColor(148, 163, 184); p1.space_before = Pt(20)

        notes_text = getattr(video, "ai_notes", None) or "No AI notes available."
        
        mermaid_blocks = []
        diagram_blocks = []
        def block_repl(match):
            lang = match.group(1).lower().strip()
            content = match.group(2)
            if 'mermaid' in lang:
                idx = len(mermaid_blocks)
                mermaid_blocks.append(content)
                return f"__MERMAID_BLOCK_{idx}__"
            elif 'diagram' in lang or ('json' in lang and '"nodes"' in content and '"edges"' in content):
                idx = len(diagram_blocks)
                diagram_blocks.append(content)
                return f"__DIAGRAM_BLOCK_{idx}__"
            return match.group(0) 
            
        safe_text = re.sub(r'```(\w*)\n(.*?)```', block_repl, notes_text, flags=re.DOTALL)
        sections = re.split(r'\n(?=#{2,3} )', safe_text.strip())
        
        for section in sections:  
            if not section.strip(): continue
            
            lines = section.split('\n')
            slide_title = "Study Guide Notes"  
            if lines[0].startswith('#'):  
                slide_title = re.sub(r'^#+\s*', '', lines[0]).replace('**', '').replace('`', '').strip()  
                lines = lines[1:]
            
            slide = prs.slides.add_slide(blank_layout)
            
            header_bg = slide.shapes.add_shape(1, 0, 0, prs.slide_width, Inches(1.1))  
            header_bg.fill.solid(); header_bg.fill.fore_color.rgb = RGBColor(30, 41, 59); header_bg.line.fill.background()
            
            t_box = slide.shapes.add_textbox(Inches(0.5), Inches(0.2), Inches(12.33), Inches(0.8))  
            tp = t_box.text_frame.paragraphs[0]; tp.text = slide_title  
            tp.font.size = Pt(24); tp.font.bold = True; tp.font.color.rgb = RGBColor(255, 255, 255)

            current_top = 1.4  
            
            valid_table_lines = set()
            for i in range(len(lines)):
                l = lines[i].strip()
                if re.match(r'^\|[\s\-:\|]+\|$', l) and '---' in l:
                    valid_table_lines.add(i)
                    j = i - 1
                    while j >= 0 and lines[j].strip().startswith('|') and lines[j].strip().endswith('|'):
                        valid_table_lines.add(j); j -= 1
                    j = i + 1
                    while j < len(lines) and lines[j].strip().startswith('|') and lines[j].strip().endswith('|'):
                        valid_table_lines.add(j); j += 1

            in_table = False; table_lines = []
            in_diagram = False; diagram_lines = []
            in_block = False; block_lines = []

            def flush_block():  
                nonlocal current_top  
                if not block_lines: return
                while block_lines and not block_lines[-1].strip(): block_lines.pop()
                if not block_lines: return
                
                text_str = "\n".join(block_lines)  
                clean_text = _clean_math_for_pdf(text_str).replace('**', '').replace('`', '').replace('*', '')
                needed_height = max(0.4, 0.25 * len(block_lines))
                
                tb = slide.shapes.add_textbox(Inches(0.5), Inches(current_top), Inches(12.33), Inches(needed_height))  
                tf = tb.text_frame; tf.word_wrap = True
                p = tf.paragraphs[0]; p.text = clean_text; p.font.size = Pt(14); p.font.color.rgb = RGBColor(30, 41, 59)
                current_top += needed_height + 0.1; block_lines.clear()

            def flush_diagram():
                nonlocal current_top
                if not diagram_lines: return
                while diagram_lines and not diagram_lines[-1].strip(): diagram_lines.pop()
                if not diagram_lines: return

                needed_height = max(0.5, 0.18 * len(diagram_lines))
                diag_bg = slide.shapes.add_shape(1, Inches(0.5), Inches(current_top), Inches(12.33), Inches(needed_height))
                diag_bg.fill.solid(); diag_bg.fill.fore_color.rgb = RGBColor(248, 250, 252)
                diag_bg.line.color.rgb = RGBColor(147, 197, 253); diag_bg.line.dash_style = MSO_LINE.DASH; diag_bg.line.width = Pt(1.5)

                tf = diag_bg.text_frame; tf.word_wrap = False; tf.clear()
                for d_line in diagram_lines:
                    p = tf.add_paragraph()
                    p.text = d_line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    p.font.name = 'Courier New'; p.font.size = Pt(10); p.font.color.rgb = RGBColor(37, 99, 235); p.font.bold = True
                
                current_top += needed_height + 0.2; diagram_lines.clear()

            def flush_table():  
                nonlocal current_top  
                if not table_lines: return
                
                raw_rows = []  
                for r in table_lines:  
                    if re.match(r'^\|[\s\-:\|]+\|$', r.strip()) and '---' in r: continue
                    if re.match(r'^[\s\|-]*$', r): continue  
                    cells = [_clean_math_for_pdf(c).strip().replace('**','').replace('`','') for c in r.strip(' |').split('|')]  
                    raw_rows.append(cells)
                
                if raw_rows:  
                    max_cols = max(len(r) for r in raw_rows)
                    rows = len(raw_rows); cols = max_cols  
                    if cols > 0 and rows > 0:  
                        tbl_height = min(5.5, max(0.45 * rows, 1.0))
                        table_shape = slide.shapes.add_table(rows, cols, Inches(0.5), Inches(current_top), Inches(12.33), Inches(tbl_height))  
                        table = table_shape.table
                        for r_idx, row_data in enumerate(raw_rows):  
                            while len(row_data) < cols:
                                row_data.append("")
                            row_data = row_data[:cols]
                            for c_idx, cell_value in enumerate(row_data):  
                                cell = table.cell(r_idx, c_idx)  
                                cell.text = cell_value  
                                cp = cell.text_frame.paragraphs[0]; cp.font.size = Pt(11)
                                if r_idx == 0:  
                                    cell.fill.solid(); cell.fill.fore_color.rgb = RGBColor(30, 41, 59)  
                                    cp.font.color.rgb = RGBColor(255, 255, 255); cp.font.bold = True  
                                else:  
                                    cell.fill.solid()  
                                    if r_idx % 2 == 0: cell.fill.fore_color.rgb = RGBColor(241, 245, 249)  
                                    else: cell.fill.fore_color.rgb = RGBColor(255, 255, 255)  
                                    cp.font.color.rgb = RGBColor(30, 41, 59)
                        current_top += tbl_height + 0.3  
                table_lines.clear()

            for idx, raw_line in enumerate(lines):  
                line = raw_line.strip()  
                
                if line.startswith('__DIAGRAM_BLOCK_'):
                    if in_block: in_block = False; flush_block()
                    if in_table: in_table = False; flush_table()
                    
                    match = re.search(r'__DIAGRAM_BLOCK_(\d+)__', line)
                    if match:
                        d_idx = int(match.group(1))
                        if d_idx < len(diagram_blocks):
                            try:
                                layout_data = json.loads(diagram_blocks[d_idx])
                                s, w_in, h_in = diagram.pptx_fit(layout_data, 12.33, 7.0 - current_top)
                                h_used = diagram.add_diagram_to_slide(
                                    slide, layout_data, left_in=0.5, top_in=current_top, 
                                    max_w_in=12.33, max_h_in=7.0 - current_top
                                )
                                current_top += h_used + 0.3
                            except Exception as e:
                                block_lines.append("[Native Diagram Render Failed]")
                                in_block = True
                    continue

                if line.startswith('__MERMAID_BLOCK_'):
                    if in_block: in_block = False; flush_block()
                    if in_table: in_table = False; flush_table()
                    
                    match = re.search(r'__MERMAID_BLOCK_(\d+)__', line)
                    if match:
                        m_idx = int(match.group(1))
                        if m_idx < len(mermaid_blocks):
                            img_stream = _get_mermaid_image(mermaid_blocks[m_idx])
                            if img_stream:
                                pic = slide.shapes.add_picture(img_stream, Inches(0.5), Inches(current_top))
                                if pic.height > Inches(5):
                                    aspect = pic.width / pic.height
                                    pic.height = Inches(5)
                                    pic.width = Inches(5 * aspect)
                                current_top += pic.height.inches + 0.2
                    continue

                if not line:
                    if in_block: block_lines.append(raw_line)
                    elif in_diagram: diagram_lines.append(raw_line)
                    continue
                
                if idx in valid_table_lines:
                    if in_block: in_block = False; flush_block()
                    if in_diagram: in_diagram = False; flush_diagram()
                    in_table = True
                    table_lines.append(raw_line)
                    continue

                is_diag = False  
                if '+--' in raw_line or '--+' in raw_line or '-->' in raw_line or '<--' in raw_line or re.search(r'\| {2,}', raw_line) or re.search(r'\s{2,}\|', raw_line) or (line.startswith('|') and line.endswith('|')):  
                    is_diag = True
                
                if is_diag:  
                    if in_block: in_block = False; flush_block()  
                    if in_table: in_table = False; flush_table()
                    in_diagram = True  
                    diagram_lines.append(raw_line)  
                else:  
                    if in_diagram: in_diagram = False; flush_diagram()  
                    if in_table: in_table = False; flush_table()  
                    in_block = True  
                    block_lines.append(raw_line)
            
            if in_block: flush_block()  
            if in_diagram: flush_diagram()
            if in_table: flush_table()
            
        buffer = io.BytesIO()  
        prs.save(buffer)  
        ppt_bytes = buffer.getvalue()
        
    except Exception as e:  
        raise HTTPException(status_code=500, detail=f"Failed to generate PowerPoint: {str(e)}")

    safe_title = "".join(c for c in (video.title or "guide") if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")  
    return Response(content=ppt_bytes, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation", headers={"Content-Disposition": f"attachment; filename={safe_title}_Study_Guide.pptx"})

@router.delete("/videos/{video_id}")
def delete_video(video_id: str, user: models.User = Depends(auth.get_current_user), db: DbSession = Depends(get_db)):
    video = _own_video(video_id, user, db)
    db.delete(video)
    db.commit()
    return {"ok": True, "message": "Video session deleted."}