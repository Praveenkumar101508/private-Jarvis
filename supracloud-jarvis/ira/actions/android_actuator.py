"""
ira/actions/android_actuator.py — EXPERIMENTAL, OFF-by-default Android actuator.

A sandboxed phone actuator for IRA, adapted (not copied) from droidclaw
(https://github.com/unitedbyai/droidclaw, MIT). We port only the screen-reading
and recovery loop — NOT droidclaw's network server (see CVE-2026-10216, mitigated
in actions/android_pairing.py). It runs fully locally: screen state comes from
`adb`/uiautomator on a USB-attached device and reasoning uses IRA's own local
(Ollama) model — nothing leaves the box.

Safety posture:
  * Disabled unless `settings.android_actuator_enabled` is True (default False).
    Every entry point short-circuits to {"status": "disabled"} when off.
  * On-screen text is UNTRUSTED (a phishing screen can carry an injection
    payload), so the screen representation handed to a model is wrapped via
    `utils.prompt_safety` and scanned for injection patterns.
  * Actuation (tap/type/swipe) is destructive and must be gated behind the
    approval guardrail + owner check at the route layer; this module never
    actuates on its own and reads screens read-only.

`adb_exec` is an injectable callable(list[str]) -> str so the loop is testable
without a device.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable, Optional

from actions import is_configured, not_configured_message
from config import get_settings
from utils.prompt_safety import check_adversarial_content, wrap_external_content

logger = logging.getLogger("ira.actions.android")

AdbExec = Callable[[list], str]

_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
_HIERARCHY_RE = re.compile(r"<hierarchy[\s\S]*?</hierarchy>", re.I)
# adb input text uses %s for spaces; reject control chars defensively.
_TEXT_SAFE_RE = re.compile(r"[\x00-\x1f]")


@dataclass
class UIElement:
    text: str
    center: tuple[int, int]
    action: str            # tap | type | longpress | scroll | read
    editable: bool = False
    clickable: bool = False
    scrollable: bool = False
    enabled: bool = True


def _attr_true(node, name: str) -> bool:
    return node.get(name, "false") == "true"


def parse_ui_xml(xml_content: str) -> list[UIElement]:
    """Parse a uiautomator accessibility dump into interactive UI elements.

    Adapted from droidclaw's sanitizer.ts (getInteractiveElements): keep nodes
    that are interactive or carry text, compute the tap centre from bounds, and
    suggest an action. Fail soft on malformed XML (screen still loading) -> [].
    """
    m = _HIERARCHY_RE.search(xml_content or "")
    if not m:
        return []
    try:
        root = ET.fromstring(m.group(0))
    except ET.ParseError:
        logger.info("uiautomator XML not parseable yet (screen loading)")
        return []

    out: list[UIElement] = []
    for node in root.iter("node"):
        bounds = node.get("bounds", "")
        bm = _BOUNDS_RE.match(bounds)
        if not bm:
            continue
        x1, y1, x2, y2 = (int(v) for v in bm.groups())
        if x2 - x1 <= 0 or y2 - y1 <= 0:
            continue  # invisible

        cls = node.get("class", "")
        clickable = _attr_true(node, "clickable")
        long_clickable = _attr_true(node, "long-clickable")
        scrollable = _attr_true(node, "scrollable")
        editable = ("EditText" in cls or "AutoCompleteTextView" in cls
                    or _attr_true(node, "editable"))
        text = node.get("text") or node.get("content-desc") or ""

        if not (clickable or long_clickable or scrollable or editable or text):
            continue

        if editable:
            action = "type"
        elif long_clickable and not clickable:
            action = "longpress"
        elif scrollable and not clickable:
            action = "scroll"
        elif clickable:
            action = "tap"
        else:
            action = "read"

        out.append(UIElement(
            text=text,
            center=((x1 + x2) // 2, (y1 + y2) // 2),
            action=action,
            editable=editable,
            clickable=clickable or long_clickable,
            scrollable=scrollable,
            enabled=node.get("enabled", "true") != "false",
        ))
    return out


def _score(el: UIElement) -> int:
    return (10 if el.enabled else 0) + (8 if el.editable else 0) + \
           (5 if el.clickable else 0) + (3 if el.text else 0)


def filter_elements(elements: list[UIElement], limit: int) -> list[UIElement]:
    """Dedupe by centre (5px buckets), score, and keep the top `limit`."""
    seen: dict[tuple[int, int], UIElement] = {}
    for el in elements:
        key = (round(el.center[0] / 5) * 5, round(el.center[1] / 5) * 5)
        if key not in seen or _score(el) > _score(seen[key]):
            seen[key] = el
    ranked = sorted(seen.values(), key=_score, reverse=True)
    return ranked[: max(1, limit)]


def compute_screen_hash(elements: list[UIElement]) -> str:
    """Stable hash of the screen for stuck-loop detection (cf. droidclaw)."""
    return ";".join(f"{e.text}|{e.center[0]},{e.center[1]}|{e.action}" for e in elements)


def screen_text(elements: list[UIElement]) -> str:
    """A compact textual screen description (the raw, pre-wrap content)."""
    lines = [
        f"- [{e.action}] {e.text!r} @ ({e.center[0]},{e.center[1]})"
        + ("" if e.enabled else " (disabled)")
        for e in elements
    ]
    return "Screen elements:\n" + "\n".join(lines) if lines else "Screen elements: (none)"


@dataclass
class RecoveryTracker:
    """Stuck-loop / repetition detection ported from droidclaw's recovery logic.

    If the same (screen, action) pair recurs `repeat_limit` times, the loop is
    stuck and the caller should stop or fall back rather than spin.
    """
    repeat_limit: int = 3
    _history: list[str] = field(default_factory=list)

    def record(self, screen_hash: str, action_sig: str) -> None:
        self._history.append(f"{screen_hash}=>{action_sig}")

    def is_stuck(self) -> bool:
        if not self._history:
            return False
        last = self._history[-1]
        return self._history.count(last) >= self.repeat_limit


# ── default adb executor ──────────────────────────────────────────────────────

def _default_adb_exec(args: list) -> str:
    import subprocess
    cfg = get_settings()
    # shell=False, argv list — no shell interpolation of on-screen content.
    proc = subprocess.run(
        [cfg.android_adb_path, *args],
        capture_output=True, text=True, timeout=20, check=False,
    )
    return proc.stdout


# ── read (non-destructive) ────────────────────────────────────────────────────

async def read_screen(*, cfg=None, adb_exec: Optional[AdbExec] = None) -> dict:
    """Capture + sanitise the current screen. READ-ONLY, fail-soft, flag-gated."""
    cfg = cfg or get_settings()
    if not is_configured("android", cfg):
        return {"status": "disabled", "message": not_configured_message("android")}
    run = adb_exec or _default_adb_exec
    try:
        xml = run(["exec-out", "uiautomator", "dump", "/dev/tty"])
    except Exception as exc:  # noqa: BLE001 — fail soft
        return {"status": "error", "message": f"adb screen read failed: {str(exc)[:160]}"}

    elements = filter_elements(parse_ui_xml(xml), cfg.android_screen_max_elements)
    raw = screen_text(elements)
    flags = check_adversarial_content(raw)
    if flags:
        logger.warning("prompt-injection patterns on Android screen: %s", flags)
    return {
        "status": "ok",
        "element_count": len(elements),
        "screen_hash": compute_screen_hash(elements),
        # Model-facing block is isolation-wrapped — on-screen text is untrusted.
        "screen": wrap_external_content(raw, source="android-screen"),
        "injection_flags": flags,
    }


# ── actuation (destructive → gated by the caller/route) ───────────────────────

def build_action_command(action: str, **params) -> list:
    """Build the adb argv for a single action. Pure; no execution."""
    if action == "tap":
        return ["shell", "input", "tap", str(int(params["x"])), str(int(params["y"]))]
    if action == "swipe":
        return ["shell", "input", "swipe", str(int(params["x1"])), str(int(params["y1"])),
                str(int(params["x2"])), str(int(params["y2"])), str(int(params.get("duration_ms", 200)))]
    if action == "key":
        return ["shell", "input", "keyevent", str(params["keycode"])]
    if action in ("type", "input_text"):
        text = str(params.get("text", ""))
        if _TEXT_SAFE_RE.search(text):
            raise ValueError("text contains control characters")
        return ["shell", "input", "text", text.replace(" ", "%s")]
    raise ValueError(f"unsupported action {action!r}")


async def act(action: str, *, cfg=None, adb_exec: Optional[AdbExec] = None, **params) -> dict:
    """Perform ONE actuation. DESTRUCTIVE — callers MUST gate behind approval.

    Still refuses when the actuator is disabled, as defence in depth.
    """
    cfg = cfg or get_settings()
    if not is_configured("android", cfg):
        return {"status": "disabled", "message": not_configured_message("android")}
    try:
        argv = build_action_command(action, **params)
    except (KeyError, ValueError) as exc:
        return {"status": "error", "message": f"Invalid action: {exc}"}
    run = adb_exec or _default_adb_exec
    try:
        run(argv)
    except Exception as exc:  # noqa: BLE001 — fail soft
        return {"status": "error", "message": f"adb action failed: {str(exc)[:160]}"}
    return {"status": "executed", "action": action, "params": params}


__all__ = [
    "UIElement", "parse_ui_xml", "filter_elements", "compute_screen_hash",
    "screen_text", "RecoveryTracker", "read_screen", "build_action_command", "act",
]
