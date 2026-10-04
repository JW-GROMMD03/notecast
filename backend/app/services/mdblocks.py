import re
import json

def _extract_braced(s, start_idx):
    """
    Safely extracts content inside balanced curly braces starting at start_idx.
    Handles nested braces (e.g., \frac{a^{2} + b}{c}) without failing.
    """
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

def _clean_math_to_html(text: str) -> str:
    """
    Robustly converts raw LaTeX math expressions and symbols into clean, readable Unicode 
    and HTML formatting so formulas render perfectly everywhere (including tables).
    """
    if not text:
        return ""
    
    t = text
    
    # 1. Remove raw LaTeX block/inline wrappers robustly using regex
    t = re.sub(r'\\\[|\\\]|\\\(|\\\)', '', t)
    t = t.replace("$$", "").replace("$", "")
    t = t.replace(r"\begin{aligned}", "").replace(r"\end{aligned}", "")
    t = t.replace(r"\begin{matrix}", "").replace(r"\end{matrix}", "")
    t = t.replace(r"\displaystyle", "")

    # 2. Robust parsing for fractions: \frac{num}{den} or \dfrac{num}{den} with nested brace support
    result_chars = []
    i = 0
    while i < len(t):
        if t[i:i+5] == '\\frac' or t[i:i+6] == '\\dfrac':
            skip_len = 6 if t[i:i+6] == '\\dfrac' else 5
            idx = i + skip_len
            while idx < len(t) and t[idx].isspace():
                idx += 1
            num, idx = _extract_braced(t, idx)
            while idx < len(t) and t[idx].isspace():
                idx += 1
            den, idx = _extract_braced(t, idx)
            
            if num is not None and den is not None:
                num_clean = _clean_math_to_html(num)
                den_clean = _clean_math_to_html(den)
                frac_html = (
                    f'<span style="display:inline-block; vertical-align:middle; text-align:center; margin: 0 3px;">'
                    f'<span style="display:block; border-bottom:1px solid #1e293b; padding-bottom:1px;">{num_clean}</span>'
                    f'<span style="display:block; padding-top:1px;">{den_clean}</span>'
                    f'</span>'
                )
                result_chars.append(frac_html)
                i = idx
                continue
        
        result_chars.append(t[i])
        i += 1
    
    t = "".join(result_chars)

    # 3. Translate common LaTeX math macros into readable Unicode equivalents
    t = re.sub(r'\\partial', '∂', t)
    t = re.sub(r'\\nabla', '∇', t)
    t = re.sub(r'\\sum', '∑', t)
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
    t = re.sub(r'\\sin', 'sin', t)
    t = re.sub(r'\\cos', 'cos', t)
    t = re.sub(r'\\tan', 'tan', t)
    t = re.sub(r'\\arctan', 'arctan', t)

    # 4. Handle HTML subscripts and superscripts
    t = re.sub(r'_\{([^}]+)\}', r'<sub>\1</sub>', t)
    t = re.sub(r'_([a-zA-Z0-9])', r'<sub>\1</sub>', t)
    t = re.sub(r'\^\{([^}]+)\}', r'<sup>\1</sup>', t)
    t = re.sub(r'\^([a-zA-Z0-9])', r'<sup>\1</sup>', t)
    
    # 5. Clean up any leftover escape characters or braces
    t = t.replace(r"\\", "<br>")
    t = t.replace("{", "").replace("}", "").replace("\\", "")
    return t

def render_html(markdown_text: str) -> str:
    """
    Renders AI markdown notes into rich, scrollable, professional HTML for the web client 
    with pristine mathematical formula translation and zero truncation.
    """
    if not markdown_text:
        return ""
        
    html = markdown_text
    
    wrapper_head = """
    <div style="max-height: 85vh; overflow-y: auto; padding: 24px; background: #ffffff; color: #1e293b; font-family: system-ui, -apple-system, sans-serif; line-height: 1.7; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
    <style>
        .web-diagram-box {
            background: #f8fafc;
            border: 1px solid #cbd5e1;
            border-radius: 10px;
            padding: 20px;
            margin: 20px 0;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        }
        .web-diagram-title {
            font-weight: 700;
            color: #0f172a;
            font-size: 1.1rem;
            margin-bottom: 15px;
            text-align: center;
        }
        .web-diagram-node {
            background: #2563eb;
            color: #ffffff;
            padding: 12px 18px;
            border-radius: 8px;
            text-align: center;
            font-weight: 600;
            font-size: 0.95rem;
            margin: 8px auto;
            max-width: 600px;
            box-shadow: 0 2px 4px rgba(37, 99, 235, 0.2);
        }
        .web-diagram-arrow {
            text-align: center;
            color: #64748b;
            font-size: 1.2rem;
            margin: 4px 0;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 16px 0;
            background: #ffffff;
        }
        th, td {
            border: 1px solid #e2e8f0;
            padding: 10px 14px;
            text-align: left;
            font-size: 0.95rem;
        }
        th {
            background: #f1f5f9;
            color: #0f172a;
            font-weight: 700;
        }
    </style>
    """
    wrapper_foot = "</div>"

    html = _clean_math_to_html(html)

    def render_web_diagram(match):
        try:
            json_str = match.group(1).strip()
            data = json.loads(json_str)
            title = data.get("title", "Process Flow")
            nodes = data.get("nodes", [])
            
            flowchart_html = [f'<div class="web-diagram-box">', f'<div class="web-diagram-title">{title}</div>']
            
            for idx, node in enumerate(nodes):
                label = node.get("label", node.get("id", ""))
                flowchart_html.append(f'<div class="web-diagram-node">{label.replace(chr(10), "<br>")}</div>')
                if idx < len(nodes) - 1:
                    flowchart_html.append('<div class="web-diagram-arrow">↓</div>')
                    
            flowchart_html.append('</div>')
            return "".join(flowchart_html)
        except Exception as e:
            return f'<div style="color: red; padding: 10px;">[Diagram Render Error: {str(e)}]</div>'
            
    html = re.sub(r'```(?:diagram|json)\s*\n(\{.*?\})\s*\n```', render_web_diagram, html, flags=re.DOTALL | re.IGNORECASE)

    html = re.sub(r'```(.*?)\n(.*?)```', r'<pre style="background: #f1f5f9; padding: 14px; border-radius: 8px; overflow-x: auto;"><code class="language-\1">\2</code></pre>', html, flags=re.DOTALL)
    html = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', html)
    
    html = re.sub(r'^### (.*?)$', r'<h3 style="color: #334155; margin-top: 24px; font-size: 1.25rem;">\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.*?)$', r'<h2 style="color: #0f172a; margin-top: 32px; font-size: 1.5rem; border-bottom: 2px solid #e2e8f0; padding-bottom: 6px;">\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^# (.*?)$', r'<h1 style="color: #1e3a8a; font-size: 2rem; font-weight: 800; margin-bottom: 16px;">\1</h1>', html, flags=re.MULTILINE)
    
    html = html.replace('\n', '<br/>')
    html = html.replace('</pre><br/>', '</pre>')
    html = html.replace('</h3><br/>', '</h3>')
    html = html.replace('</h2><br/>', '</h2>')
    html = html.replace('</h1><br/>', '</h1>')
    html = html.replace('</div><br/>', '</div>')

    return wrapper_head + html + wrapper_foot