"""
IRA Advanced Design Tools — Feature #2.

Generate HTML/CSS mockups, Mermaid diagrams, SVG illustrations, slide decks,
Canva-style layouts, wireframes, and system architecture diagrams from chat.

POST /design/generate  — generate a design artifact from a prompt (SSE)
GET  /design/download/{design_id} — download HTML/SVG artifact

Trigger phrases:
  "design a landing page...", "create a wireframe...", "draw a diagram...",
  "make a flowchart...", "generate a system diagram...", "create a mockup...",
  "build a UI for...", "sketch a layout...", "create a Mermaid diagram..."
"""

from __future__ import annotations

import io
import json as _json
import logging
import re
import time
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from api.middleware.auth import require_auth
from utils.llm import chat_complete

router = APIRouter(prefix="/design", tags=["design"])
logger = logging.getLogger("ira.design_tools")

# In-memory store (id → (content_bytes, filename, mimetype))
_DESIGN_STORE: dict[str, tuple[bytes, str, str]] = {}

# Trigger detection
_DESIGN_RE = re.compile(
    r"\b(design\s+(a\s+)?(landing.?page|page|ui|interface|mockup|wireframe|layout|dashboard|form|component)|"
    r"create\s+(a\s+)?(wireframe|mockup|diagram|flowchart|ui|layout|sketch|slide|canva)|"
    r"draw\s+(a\s+)?(diagram|flowchart|chart|graph|architecture|sequence|er.?diagram|class.?diagram)|"
    r"generate\s+(a\s+)?(diagram|flowchart|mockup|wireframe|ui|layout|architecture)|"
    r"make\s+(a\s+)?(diagram|flowchart|wireframe|mockup|ui|landing.?page)|"
    r"build\s+(a\s+)?(ui|interface|layout|dashboard|component)|"
    r"(mermaid|sequence.?diagram|er.?diagram|class.?diagram|gantt|mind.?map|system.?diagram))\b",
    re.I,
)

_TYPE_RE = re.compile(
    r"\b(mermaid|flowchart|sequence|er.?diagram|class.?diagram|gantt|mindmap|pie.?chart|"
    r"landing.?page|dashboard|wireframe|mockup|ui|html|svg|architecture)\b",
    re.I,
)


def is_design_request(query: str) -> bool:
    return bool(_DESIGN_RE.search(query))


def _detect_design_type(query: str) -> Literal["html", "mermaid", "svg"]:
    m = _TYPE_RE.search(query)
    if not m:
        return "html"
    t = m.group(1).lower()
    if t in ("mermaid", "flowchart", "sequence", "er-diagram", "er diagram",
             "class-diagram", "class diagram", "gantt", "mindmap", "pie chart",
             "architecture"):
        return "mermaid"
    if t == "svg":
        return "svg"
    return "html"


# ── Request model ─────────────────────────────────────────────────────────────

class DesignRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000)
    design_type: Optional[Literal["html", "mermaid", "svg"]] = None
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


# ── System prompts ────────────────────────────────────────────────────────────

_HTML_SYSTEM = """\
You are a world-class UI/UX designer and front-end developer.
Generate a complete, self-contained, beautiful HTML file.

Requirements:
- Single HTML file with embedded CSS and optional inline JS
- Modern design: clean typography, good spacing, subtle shadows, smooth animations
- Use CSS variables for theming — dark mode compatible
- Mobile responsive (CSS Grid or Flexbox)
- No external dependencies (no CDN links) — everything must be inline
- Include a realistic design with placeholder content matching the request
- Output ONLY the complete HTML — no markdown, no code fences, no explanation

Style guide:
- Background: #0f0f12 (dark) or #ffffff (light)
- Primary accent: #6366f1 (indigo) or user-specified
- Font stack: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif
- Rounded corners, subtle glassmorphism effects where appropriate
"""

_MERMAID_SYSTEM = """\
You are an expert software architect and diagram creator.
Generate a complete Mermaid diagram wrapped in a beautiful HTML page.

Requirements:
- Create a valid Mermaid diagram (flowchart, sequence, ER, class, Gantt, mindmap, etc.)
- Choose the best diagram type for the request
- Include descriptive labels and clear relationships
- Wrap it in a self-contained HTML page that renders the diagram via Mermaid CDN
- Add a title and brief description above the diagram
- Dark theme with proper contrast

Output format — a complete HTML file like:
<!DOCTYPE html><html>...<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
<div class="mermaid">flowchart TD...</div>...
"""

_SVG_SYSTEM = """\
You are a professional graphic designer specialising in SVG illustrations.
Generate a complete, self-contained SVG illustration.

Requirements:
- Pure SVG with embedded styles (no external files)
- Viewbox="0 0 800 600" or appropriate dimensions
- Include gradients, shadows (filters), and modern design elements
- Responsive with width="100%" height="auto"
- Add a title element for accessibility
- Output ONLY the SVG markup — no HTML wrapper, no markdown
"""


async def _generate_design_content(prompt: str, dtype: str) -> str:
    system = {"html": _HTML_SYSTEM, "mermaid": _MERMAID_SYSTEM, "svg": _SVG_SYSTEM}[dtype]
    msgs = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    return await chat_complete(msgs, use_deep=True, max_tokens=8192, temperature=0.3)


def _wrap_mermaid_in_html(content: str) -> str:
    """If LLM returned only mermaid code, wrap it in HTML."""
    if content.strip().startswith("<!DOCTYPE") or content.strip().startswith("<html"):
        return content
    # Extract mermaid code from code fences if present
    mermaid_match = re.search(r"```(?:mermaid)?\n([\s\S]+?)```", content)
    mermaid_code = mermaid_match.group(1) if mermaid_match else content
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>IRA Diagram</title>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <style>
    body {{ background: #0f0f12; color: #e5e7eb; font-family: -apple-system, sans-serif;
           display: flex; flex-direction: column; align-items: center; padding: 2rem; }}
    .diagram-container {{ background: #1a1a2e; border-radius: 12px; padding: 2rem;
                          max-width: 1000px; width: 100%; box-shadow: 0 4px 24px rgba(0,0,0,0.4); }}
    h1 {{ color: #6366f1; margin-bottom: 1rem; font-size: 1.25rem; }}
    .mermaid {{ background: transparent; }}
  </style>
</head>
<body>
  <div class="diagram-container">
    <h1>Generated by IRA Design Tools</h1>
    <div class="mermaid">
{mermaid_code}
    </div>
  </div>
  <script>mermaid.initialize({{ startOnLoad: true, theme: 'dark' }});</script>
</body>
</html>"""


def _clean_html_output(content: str) -> str:
    """Strip markdown code fences if LLM wrapped HTML in them."""
    content = re.sub(r"^```(?:html)?\n", "", content.strip())
    content = re.sub(r"\n```$", "", content.strip())
    return content


def _clean_svg_output(content: str) -> str:
    content = re.sub(r"^```(?:svg|xml)?\n", "", content.strip())
    content = re.sub(r"\n```$", "", content.strip())
    return content


# ── SSE generate endpoint ─────────────────────────────────────────────────────

@router.post("/generate")
async def design_generate(
    req: DesignRequest,
    _user: str = Depends(require_auth),
):
    """Generate a design artifact (HTML mockup, Mermaid diagram, SVG) via SSE."""
    dtype = req.design_type or _detect_design_type(req.prompt)

    async def gen():
        t0 = time.monotonic()
        type_labels = {"html": "HTML mockup", "mermaid": "diagram", "svg": "SVG illustration"}
        design_name = re.sub(r"[^a-z0-9_]", "_", req.prompt[:40].lower()).strip("_")

        yield {"data": _json.dumps({"token": f"🎨 Generating {type_labels[dtype]}…\n\n"})}

        try:
            content = await _generate_design_content(req.prompt, dtype)

            yield {"data": _json.dumps({"token": "✅ Design generated — preparing preview…\n"})}

            # Process content based on type
            if dtype == "html":
                final_content = _clean_html_output(content)
                file_bytes = final_content.encode("utf-8")
                filename = f"ira_{design_name}.html"
                mimetype = "text/html"
            elif dtype == "mermaid":
                final_content = _wrap_mermaid_in_html(content)
                file_bytes = final_content.encode("utf-8")
                filename = f"ira_{design_name}_diagram.html"
                mimetype = "text/html"
            else:  # svg
                final_content = _clean_svg_output(content)
                file_bytes = final_content.encode("utf-8")
                filename = f"ira_{design_name}.svg"
                mimetype = "image/svg+xml"

            design_id = str(uuid.uuid4())[:8]
            _DESIGN_STORE[design_id] = (file_bytes, filename, mimetype)

            latency = int((time.monotonic() - t0) * 1000)
            yield {"data": _json.dumps({
                "design_created": True,
                "design_id": design_id,
                "filename": filename,
                "design_type": dtype,
                "size_kb": len(file_bytes) // 1024,
                "preview_url": f"/api/v1/design/download/{design_id}",
            })}
            yield {"data": _json.dumps({
                "token": (
                    f"\n🎨 **{filename}** ready!\n"
                    f"Type: {type_labels[dtype]} · Size: {len(file_bytes)//1024}KB\n\n"
                    f"[🔍 Preview]({f'/api/v1/design/download/{design_id}'})"
                )
            })}
        except Exception as e:
            logger.error(f"Design generation error: {e}", exc_info=True)
            yield {"data": _json.dumps({"token": f"\n❌ Design generation error: {str(e)[:200]}"})}

        yield {"data": _json.dumps({
            "done": True, "agent": "design_tools",
            "latency_ms": int((time.monotonic() - t0) * 1000),
        })}

    return EventSourceResponse(gen())


# ── Download endpoint ─────────────────────────────────────────────────────────

@router.get("/download/{design_id}")
async def design_download(
    design_id: str,
    _user: str = Depends(require_auth),
):
    """Download / preview a generated design artifact."""
    entry = _DESIGN_STORE.get(design_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Design not found or expired.")
    file_bytes, filename, mimetype = entry
    # For HTML/SVG, serve inline so browser can render it
    disposition = "inline" if mimetype in ("text/html", "image/svg+xml") else f'attachment; filename="{filename}"'
    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=mimetype,
        headers={"Content-Disposition": disposition},
    )
