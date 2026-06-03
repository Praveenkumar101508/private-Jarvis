"""
ira/skills/_common.py — shared helpers for IRA agents ported to Hermes (Option A).

Each ported agent = a SKILL.md persona (in its dir here) + a thin module that gathers
IRA-side context (active tools, DB reads, memory all stay in IRA) and routes the
reasoning through the Hermes bridge. These helpers load the persona and assemble the
request so each per-skill module stays tiny.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from hermes_bridge import HermesBridge

_SKILLS_DIR = Path(__file__).resolve().parent


def load_persona(skill_name: str, **subs: object) -> str:
    """Return a skill's persona = its SKILL.md body (after the YAML frontmatter),
    with {placeholder} substitutions applied (e.g. owner_name)."""
    md = (_SKILLS_DIR / skill_name / "SKILL.md").read_text(encoding="utf-8")
    if md.startswith("---"):
        parts = md.split("---", 2)  # ['', frontmatter, body]
        md = parts[2] if len(parts) == 3 else md
    md = md.strip()
    for key, val in subs.items():
        md = md.replace("{" + key + "}", str(val))
    return md


def run_skill(
    skill_name: str,
    query: str,
    *,
    context_blocks: Optional[Sequence[str]] = None,
    bridge: Optional[HermesBridge] = None,
    session_key: Optional[str] = None,
    **subs: object,
) -> str:
    """Persona (+ optional IRA-gathered context blocks) -> Hermes bridge -> reply text."""
    bridge = bridge or HermesBridge()
    system = load_persona(skill_name, **subs)
    blocks = [b for b in (context_blocks or []) if b]
    if blocks:
        system += "\n\n" + "\n\n".join(blocks)
    return bridge.ask(query, system=system, session_key=session_key)


__all__ = ["load_persona", "run_skill"]
