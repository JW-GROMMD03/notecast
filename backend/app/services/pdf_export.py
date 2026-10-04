import io
import markdown
from weasyprint import HTML


def generate_notecast_pdf(title: str, channel: str, note_sections: list, transcript_segments: list, visual_events: list) -> bytes:
    """
    Compiles note sections, diagrams, and transcripts into a professional PDF
    featuring the NoteCast logo, professional typography, and a background watermark.
    Includes robust fallback handling if structured database notes are not yet generated.
    """
    
    sections_html = ""

    # 1. Use structured note sections if they exist in the database
    if note_sections:
        for idx, section in enumerate(note_sections, 1):
            heading = getattr(section, "heading", f"Section {idx}")
            body_md = getattr(section, "body_md", "")
            body_html = markdown.markdown(body_md, extensions=['extra', 'codehilite', 'tables'])
            
            sections_html += f"""
            <div class="note-section">
                <h2>{heading}</h2>
                <div class="note-body">
                    {body_html}
                </div>
            </div>
            """
            
            assets = getattr(section, "assets", [])
            if assets:
                sections_html += '<div class="asset-grid">'
                for asset in assets:
                    storage_key = getattr(asset, "storage_key", "")
                    description = getattr(asset, "description", "")
                    if storage_key:
                        clean_path = storage_key.lstrip("/")
                        sections_html += f"""
                        <div class="asset-card">
                            <img src="{clean_path}" alt="Diagram capture" />
                            <p class="asset-desc">{description}</p>
                        </div>
                        """
                sections_html += '</div>'
    
    # 2. Fallback: Automatically format transcript and visual events if notes are pending
    else:
        sections_html += """
        <div class="note-section">
            <h2>Session Transcript & Master Summary</h2>
        """
        if transcript_segments:
            transcript_text = " ".join([getattr(t, "text", "") for t in transcript_segments])
            sections_html += f"<p>{transcript_text}</p>"
        else:
            sections_html += "<p><em>No audio transcript records found for this session. Reviewing visual captures below.</em></p>"
        sections_html += "</div>"

        if visual_events:
            sections_html += """
            <div class="note-section">
                <h2>Captured Whiteboard Diagrams & Slides</h2>
                <div class="asset-grid">
            """
            for event in visual_events:
                storage_key = getattr(event, "storage_key", "")
                ocr_text = getattr(event, "ocr_text", "") or "Whiteboard / Slide capture"
                if storage_key:
                    clean_path = storage_key.lstrip("/")
                    sections_html += f"""
                    <div class="asset-card">
                        <img src="{clean_path}" alt="Visual capture" />
                        <p class="asset-desc">{ocr_text}</p>
                    </div>
                    """
            sections_html += "</div></div>"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>{title} - NoteCast Master Study Guide</title>
        <style>
            @page {{
                size: A4;
                margin: 20mm 20mm 20mm 20mm;
                @bottom-right {{
                    content: "Page " counter(page) " of " counter(pages);
                    font-size: 8pt;
                    color: #94a3b8;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                }}
                @bottom-left {{
                    content: "NoteCast Professional Study Guide";
                    font-size: 8pt;
                    color: #94a3b8;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                }}
            }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                line-height: 1.6;
                color: #1e293b;
                background-color: #ffffff;
                margin: 0;
                padding: 0;
            }}
            /* Fixed diagonal background watermark */
            .watermark {{
                position: fixed;
                top: 40%;
                left: 10%;
                transform: rotate(-35deg);
                font-size: 85pt;
                color: rgba(148, 163, 184, 0.08);
                font-weight: 900;
                z-index: -1000;
                text-transform: uppercase;
                letter-spacing: 15px;
                pointer-events: none;
            }}
            .brand-header {{
                display: flex;
                align-items: center;
                justify-content: space-between;
                border-bottom: 2px solid #e2e8f0;
                padding-bottom: 15px;
                margin-bottom: 25px;
            }}
            .brand-logo {{
                font-size: 18pt;
                font-weight: bold;
                color: #0f172a;
                display: flex;
                align-items: center;
                gap: 8px;
            }}
            .brand-mark {{
                background: #0f172a;
                color: #ffffff;
                padding: 2px 8px;
                border-radius: 4px;
                font-weight: bold;
            }}
            .video-title-block {{
                margin-bottom: 30px;
            }}
            .video-title-block h1 {{
                font-size: 22pt;
                color: #0f172a;
                margin: 0 0 8px 0;
                line-height: 1.3;
            }}
            .video-meta {{
                font-size: 10pt;
                color: #64748b;
            }}
            .note-section {{
                margin-bottom: 25px;
                page-break-inside: avoid;
            }}
            h2 {{
                font-size: 14pt;
                color: #0f172a;
                border-left: 4px solid #3b82f6;
                padding-left: 10px;
                margin-top: 20px;
                margin-bottom: 10px;
            }}
            p {{
                font-size: 10pt;
                margin: 0 0 10px 0;
                text-align: justify;
            }}
            ul, ol {{
                font-size: 10pt;
                margin-top: 0;
                padding-left: 20px;
            }}
            li {{
                margin-bottom: 5px;
            }}
            code {{
                background: #f1f5f9;
                padding: 2px 5px;
                border-radius: 4px;
                font-size: 9pt;
                color: #0f172a;
                border: 1px solid #e2e8f0;
            }}
            pre {{
                background: #f8fafc;
                padding: 12px;
                border-radius: 6px;
                border: 1px solid #e2e8f0;
                font-size: 8.5pt;
                overflow-x: auto;
            }}
            blockquote {{
                border-left: 3px solid #cbd5e1;
                margin: 0;
                padding-left: 12px;
                color: #475569;
                background: #f8fafc;
                padding-top: 8px;
                padding-bottom: 8px;
            }}
            .asset-grid {{
                margin-top: 10px;
                margin-bottom: 15px;
                page-break-inside: avoid;
            }}
            .asset-card {{
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                padding: 10px;
                margin-bottom: 10px;
                text-align: center;
            }}
            .asset-card img {{
                max-width: 100%;
                height: auto;
                border-radius: 4px;
                max-height: 250px;
                object-fit: contain;
            }}
            .asset-desc {{
                font-size: 8.5pt;
                color: #64748b;
                margin-top: 8px;
                margin-bottom: 0;
            }}
        </style>
    </head>
    <body>
        <div class="watermark">NOTECAST</div>

        <div class="brand-header">
            <div class="brand-logo">
                <span class="brand-mark">§</span> NoteCast Masterclass
            </div>
            <div style="font-size: 9pt; color: #64748b;">Verified Study Guide</div>
        </div>

        <div class="video-title-block">
            <h1>{title}</h1>
            <div class="video-meta">Creator: <strong>{channel}</strong> &bull; Generated by NoteCast AI</div>
        </div>

        <div class="notes-container">
            {sections_html}
        </div>
    </body>
    </html>
    """

    pdf_buffer = io.BytesIO()
    HTML(string=html_content).write_pdf(pdf_buffer)
    pdf_buffer.seek(0)
    return pdf_buffer.read()