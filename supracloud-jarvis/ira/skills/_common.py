"""
ira/skills/_common.py — shared helpers for IRA agents ported to Cortex (Option A).

Each ported agent = a SKILL.md persona (in its dir here) + a thin module that gathers
IRA-side context (active tools, DB reads, memory all stay in IRA) and routes the
reasoning through the Cortex bridge. These helpers load the persona and assemble the
request so each per-skill module stays tiny.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from cortex_bridge import CortexBridge

_SKILLS_DIR = Path(__file__).resolve().parent

# IRA skills are reasoning-only (Option A: IRA runs the tools/DB and passes results in
# as context). The no-tools constraint is ENFORCED by the bridge: run_skill calls it in
# reasoning_only mode, which omits --accept-hooks (so Cortex can't auto-accept a tool/
# hook call) and prepends a hardened no-tools directive (see cortex_bridge.CortexBridge.
# ask). This replaced the prior soft, prompt-only directive that an 8B model could ignore.


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
    bridge: Optional[CortexBridge] = None,
    session_id: Optional[str] = None,
    user_key: Optional[str] = None,
    session_key: Optional[str] = None,
    **subs: object,
) -> str:
    """Persona (+ optional IRA-gathered context blocks) -> Cortex bridge -> reply text.

    Forwards the session headers to the bridge: ``session_id`` (thread continuity)
    and ``user_key`` (stable per-user memory scope). ``session_key`` is a deprecated
    alias for ``user_key`` kept for callers that haven't migrated.
    """
    bridge = bridge or CortexBridge()
    system = load_persona(skill_name, **subs)
    blocks = [b for b in (context_blocks or []) if b]
    if blocks:
        system += "\n\n" + "\n\n".join(blocks)
    return bridge.ask(
        query, system=system, reasoning_only=True,
        session_id=session_id, user_key=user_key, session_key=session_key,
    )


__all__ = ["load_persona", "run_skill"]
