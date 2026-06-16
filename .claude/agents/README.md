# IRA development sub-agents

These are **development-time** Claude Code sub-agents — they help build and review
IRA. They are **not** part of IRA's runtime and are never loaded by the application.

| Agent | Use for |
| --- | --- |
| `backend-architect` | API/data-model/reliability design for the FastAPI backend |
| `frontend-developer` | the Next.js frontend (components, performance, a11y) |
| `code-reviewer` | reviewing a diff before commit (correctness/security/tests) |
| `api-tester` | designing/extending the pytest suite, esp. route + adversarial tests |

Adapted from [agency-agents](https://github.com/msitarzewski/agency-agents) (MIT).
Provenance and license: `third_party/agency-agents/`.

## Phase 4, part 2 — should these personas inform IRA's *runtime* routing?

**Decision: No — keep them dev-time only; IRA's runtime routing is unchanged.**

Rationale (inspected before deciding):

- **IRA already has a runtime specialist layer.** `ira/agents/` ships its own
  user-facing specialists (researcher, coding_agent, architect, executor, creator,
  career, tutor, …) coordinated by `ira/agents/supervisor.py` + `graph.py`, plus a
  5-agent "expert mode". A persona layer (`ira/agents/grok_personality.py`) defines
  IRA's single, consistent voice.
- **`ira/router.py` is a security gate, not a persona selector.** It deterministically
  (regex) blocks non-owners from restricted domains, fail-closed. Routing the
  *security* decision through engine-selected personas would weaken that guarantee —
  exactly what the router's docstring warns against — so these personas must not sit
  on that path.
- **Domain mismatch.** agency-agents are a software *agency* (backend/frontend/QA/
  marketing/sales). IRA is a personal assistant; injecting "frontend developer" or
  "backend architect" personas into its user-facing routing would be redundant with
  IRA's own specialists and off-domain for most user queries.

If IRA ever grows a dedicated "build/ship software for the owner" mode, the
adaptation worth borrowing is agency-agents' **structured-deliverable** pattern
(explicit priority tiers, checklists, success metrics) — folded into IRA's *own*
persona layer, not by importing these files at runtime.
