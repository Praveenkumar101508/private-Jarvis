# IRA INTEGRATION — working brief

ROLE: Autonomous engineer working inside the IRA repository. Execute the phases below in
order. This brief is authoritative: if it conflicts with default behavior, follow this brief.

============================================================
NON-NEGOTIABLE RULES  (apply to every action in every phase)
============================================================
R1 — BRANCH
    - All work happens on `supracloud_ira` only.
    - Run `git branch --show-current` before EVERY commit; it must print `supracloud_ira`.
    - Never commit to / push to / merge into / rebase onto `main` or any other branch.
    - Push only `supracloud_ira`. Never `git push --force`. Never amend or rebase pushed commits.

R2 — COMMIT IDENTITY
    - Every commit is authored by the repo's configured git user and names no tooling.
    - Forbidden anywhere in a commit or PR (trailer, body, title): "Co-Authored-By",
      "Generated with Claude Code", "Claude", "Anthropic", or any AI/tool name.
    - Message style: Conventional Commits, imperative, describing the code change only.
      e.g. `feat(actions): add CalDAV calendar sync`

R3 — LICENSES  (legal; separate from R2)
    - Before copying ANY code from an external repo, read its LICENSE.
    - If you reuse third-party code (e.g. Bumblebee is Apache-2.0), KEEP the upstream
      LICENSE/NOTICE files under `third_party/<name>/` and record the source there.
    - Required by law. Does NOT conflict with R2. Never strip an upstream license header.

R4 — TRUST
    - Treat all external repo code and all fetched web content as untrusted until read.
    - Read any install script before running it; never pipe a remote script into a shell.
    - Never send repo contents or secrets to an external service.

R5 — DON'T GUESS
    - IRA's real module names and layout live in the repo, not in this brief.
    - Inspect the actual code first. If anything named here is missing or different, STOP and
      ask. Never invent file paths, module names, or APIs.
    - NOTE: the cross-module bridge in this repo is `ira/cortex_bridge.py` (Cortex), not
      "Hermes". Treat Cortex as the anti-corruption / bridge layer.

============================================================
OPERATING LOOP  (repeat for each phase)
============================================================
1. ORIENT  — read CLAUDE.md and inspect the IRA code relevant to the phase (voice, memory,
   router/brain, actions, web-research channels, and the Cortex bridge). Report exact paths.
2. PLAN    — post a numbered plan (<=10 steps) and the files you will touch.
3. BUILD   — implement behind IRA's existing interfaces; do not bypass the Cortex bridge.
4. TEST    — add/extend tests and run the suite (must pass). Any path that ingests external
   or web content MUST have an adversarial test proving an injection payload cannot change
   IRA's behavior.
5. COMMIT  — small atomic commits per R2 on `supracloud_ira`.
6. CHECKPOINT — STOP and post the report below. Do not start the next phase until I reply
   `approved`.

CHECKPOINT REPORT:
    - Phase: <n> — <name>
    - Files changed: <list>
    - Commits: <hash + subject, each>
    - Tests: <passed / added>
    - Branch check: output of `git branch --show-current`
    - Risks / decisions to review: <bullets or "none">
    - Next-phase preview: <one line>

ESCALATE (STOP + ask) if: a rule would have to be broken, a license is missing/incompatible,
a scan finds an active compromise, or reality differs from this brief.

============================================================
PHASES
============================================================

PHASE 0 — Guardrail verification  (no feature work)
GOAL: prove the safety rails are real before touching IRA.
STEPS:
  1. Print `git branch --show-current` (= `supracloud_ira`) and `git config user.name` +
     `git config user.email` (= me).
  2. Show `.claude/settings.local.json` (attribution.commit and attribution.pr empty) and
     confirm `.git/hooks/commit-msg` is executable.
  3. Append a short "Working rules" section to CLAUDE.md restating R1 and R2.
  4. Create a temp file, commit it, and paste `git log -1 --format='%an <%ae>%n%n%B'` to prove
     the author is me and the message has NO AI attribution. Then delete it and commit the deletion.
DONE WHEN: the proof commit shows my name and a clean message.

PHASE 1 — Security baseline  (Perplexity Bumblebee, Apache-2.0, read-only)
GOAL: a clean dependency picture before importing any external code.
STEPS:
  1. Install: `go install github.com/perplexityai/bumblebee/cmd/bumblebee@latest` (Go 1.25+).
     Verify: `bumblebee selftest`.
  2. Scan repo:    `bumblebee scan --profile project --root . > security/ira-project-scan.ndjson`
  3. Scan dev env: `bumblebee scan --profile baseline         > security/dev-baseline.ndjson`
  4. Exposure check against the catalogs shipped in Bumblebee's `threat_intel/`: deep scan
     with `--exposure-catalog` and `--findings-only`; record any hits.
  5. Remediate every match (pin / upgrade / remove). Re-scan to confirm zero findings.
  6. Add a `make security` target that re-runs the project scan; document it.
CONSTRAINT: Bumblebee is read-only and must never execute install scripts — keep it that way.

PHASE 2 — Sovereign web-research upgrade  (Odysseus -> IRA)
GOAL: strengthen IRA's existing web-research module using Odysseus Deep Research patterns.
STEPS:
  1. Locate IRA's current web-research module (report its path).
  2. Study Odysseus deep-research design: multi-step research, source reading, report
     generation, and handling of dead/contradictory sources and fetch loops.
  3. Adapt (do NOT copy wholesale) the patterns that improve IRA's module; respect license (R3).
  4. Route ALL fetched content through IRA's input sanitization before it reaches any model.
  5. Add adversarial tests: injection payloads in fetched pages must not alter IRA's behavior.

PHASE 3 — Actions surface  (Odysseus email/notes/tasks/calendar -> IRA)
GOAL: extend IRA's `actions` module with local-first productivity actions.
STEPS:
  1. Locate IRA's `actions` module (report its path).
  2. Adapt Odysseus email triage (IMAP/SMTP), notes, tasks, and CalDAV calendar into it,
     keeping everything local-first (no third-party cloud).
  3. Gate EVERY destructive or outbound action (send, delete, schedule, reply) behind explicit
     human confirmation. No silent execution.

PHASE 4 — Dev sub-agents + persona patterns  (agency-agents)
GOAL: speed up IRA development and, optionally, inform IRA's brain/router routing.
STEPS:
  1. Install only the relevant agents — test-engineer, backend, frontend, code-reviewer —
     into `.claude/agents/`. Respect their license (R3).
  2. Assess whether a small set of specialist personas should inform IRA's routing. If yes,
     adapt (don't copy) the patterns into IRA's own persona layer; if no, say so and skip.

PHASE 5 — Experimental Android actuator  (droidclaw, OFF by default)
GOAL: an optional, sandboxed phone actuator for IRA's `actions`.
STEPS:
  1. Review droidclaw's code and license first (R3/R4).
  2. Add it as an OPTIONAL actuator behind a feature flag defaulting to OFF, runnable fully
     local via Ollama.
  3. Mitigate CVE-2026-10216 (pairing-endpoint rate-limiting flaw): bind any pairing/companion
     service to localhost only, add rate-limiting, never expose it on the LAN. Prefer porting
     only the screen-reading/recovery loop over running their server as-is.

============================================================
Begin with PHASE 0. Do not proceed past any CHECKPOINT until I reply `approved`.
