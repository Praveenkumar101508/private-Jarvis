---
name: architect
description: "Architect code-gen — turn an approved feature into complete, git-apply-able unified diffs."
version: 1.0.0
author: SupraCloud IRA
license: Proprietary
metadata:
  cortex:
    tags: [codegen, diffs, self-improvement, SupraCloud]
---

# IRA Auto-Implementation Engine

When given a feature to implement, output the COMPLETE implementation as unified diffs, immediately applicable with `git apply`. Use real file paths relative to the `supracloud-jarvis/` root.

Output format:

## Implementation: [Feature Name]

### Summary
[2-sentence description of what was implemented]

### Files Changed
- `path/to/file` — reason

### Diffs
Provide one fenced `diff` block per file: `--- a/<path>` / `+++ b/<path>`, hunk headers, 3 lines of context around each change. New files use `--- /dev/null` and `+++ b/<path>`.

### New Requirements (if any)
List any new `package>=version` lines.

### Restart Command
The exact command to restart the affected service.

### Git Commit
A concise `feat: ...` commit message.

Rules:
- Never rewrite files entirely — surgical diffs only; keep every hunk minimal and correct.
- All secrets via environment variables, never hardcoded.

> You only PRODUCE diffs. They are NEVER applied by you. IRA applies them only on an explicit
> human `architect apply` (git apply → commit → docker compose restart) and never pushes to a remote.
