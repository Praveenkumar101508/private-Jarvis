# README polish report

**Scope:** editorial/formatting pass over the already-merged README.md (the version
documented in `docs/README_UPDATE_REPORT.md`). No new features were added or
removed; the model-routing, Deep Intelligence Mode, answer-quality, and
memory-safety sections are all kept as-is in substance.

## Wording softened

- **Security section opener.** Replaced:

  > "IRA is built to be exposed to the internet without flinching."

  with:

  > "IRA includes a defense-in-depth security architecture for local and
  > controlled deployments, but any internet-exposed deployment still requires
  > production hardening, monitoring, and security review."

  This was the one sentence in the README that implied internet exposure was
  already safe without qualification — corrected per the brief.

- **Hero badge.** The `Local-first` badge read "runs 100% on-device," an
  absolute claim that doesn't hold once Deep Intelligence Mode is approved and
  wired to an external executor. Changed to "runs local-first by default" —
  consistent with the rest of the README's local-first-by-default framing and
  with the Deep Intelligence Mode section's actual behavior.

- Reviewed the rest of the file for the overclaim patterns called out in the
  brief (`enterprise-ready`, `banking`/`retail` as a product claim, absolute
  "nothing leaves the machine," external API already wired by default,
  internet exposure declared safe). None of those were found elsewhere — the
  existing "What IRA is — and isn't" section (kept unchanged per the brief)
  already states plainly that IRA is not a finished enterprise SaaS product,
  not a banking/retail product, and not a system that silently calls external
  APIs. The one narrow "nothing here phones home" comment (in the Quick Start
  `cp .env.example .env` step) was left as-is: it describes that specific
  copy command, not a global privacy claim about the running app, and remains
  accurate.

## Formatting fixed

- Reformatted the whole file with `prettier --prose-wrap always --print-width
100` (previously `prettier` defaulted to `proseWrap: preserve`, which had
  left many paragraphs, bullet points, and blockquote lines as very long
  single lines — several exceeded 400–500 characters in the raw source).
  Prettier's markdown formatter wraps prose, list items (with correct
  continuation indentation), and blockquotes (repeating the `>` marker per
  line) while leaving fenced code blocks, the Mermaid diagram, and GFM tables
  untouched, since those must stay on single logical lines to render/parse
  correctly.
- Verified after the reformat: the Mermaid `flowchart TB` block is unchanged
  and still fenced with ` ```mermaid ` / ` ``` `; all three GFM tables (agent
  roster, answer-policy task types, Reflexion scoring, security layers) are
  still valid pipe-table syntax with intact header separators; the two
  ASCII-pipeline code blocks and the `ollama pull` / env-var code blocks are
  untouched.
- Re-ran `prettier --check` after the manual wording edits — the file still
  passes with no formatting diffs.

## Links checked

All seven links named in the brief, resolved from the repo root:

| Link                                                       | Status |
| ---------------------------------------------------------- | ------ |
| `docs/MODEL_ROUTING_VERIFICATION_REPORT.md`                | exists |
| `supracloud-jarvis/ira/docs/MODEL_SELECTION.md`            | exists |
| `supracloud-jarvis/ira/docs/ANSWER_QUALITY_SYSTEM.md`      | exists |
| `docs/ANSWER_QUALITY_IMPLEMENTATION_REPORT.md`             | exists |
| `supracloud-jarvis/ira/config/model_selection.env.example` | exists |
| `supracloud-jarvis/LOCAL_SETUP.md`                         | exists |
| `supracloud-jarvis/TAILSCALE_SETUP.md`                     | exists |

Also re-checked the other README links (unaffected by this pass, but touched
by the prose-wrap):`supracloud-jarvis/ira/requirements-test.txt`,
`supracloud-jarvis/.env.example`, `supracloud-jarvis/start-ira.ps1`,
`supracloud-jarvis/docker-compose.cloud.yml`, `assets/ira-banner.svg`,
`assets/ira-demo.svg`, and the in-page anchors `#model-routing`,
`#deep-intelligence-mode-optional-consent-gated`, and `#testing`. All
resolve.

**No links are missing.**

## Overclaiming check

- No "enterprise-ready" claim present.
- No banking/retail product claim present — the "IRA is not (yet)" section
  explicitly disclaims this.
- No absolute "nothing ever leaves the machine" claim; every local-only
  statement in the file is scoped to a mode (`IRA_PRIVACY_MODE=local_only`)
  or gated by the consent/master-switch/executor conditions.
- No claim that the external API is wired or enabled by default —
  `IRA_ALLOW_EXTERNAL_API=false` and "no external executor ships with IRA" are
  both stated explicitly.
- Internet exposure is no longer described as safe by default; the Security
  section now says production hardening/monitoring/review is still required.

**README now avoids overclaiming: YES.**

## Tests run

```
cd supracloud-jarvis/ira
python -m pytest tests/reasoning -q
→ 126 passed
```

No code changed in this pass, so this run is a sanity check that the
polish-only README edit didn't touch anything test-relevant (it didn't —
`README.md` and this report are the only files changed).

## Follow-up verification: raw Markdown structure audit

A second pass specifically targeted the "raw Markdown still looks compressed"
concern, wording/content unchanged. Three independent, script-based checks
were run against the live `README.md` (fence-aware, so bash comments inside
code blocks are not mistaken for headings):

1. **Heading isolation** — every line matching `^#{1,6}\s` outside a fenced
   block was checked for a blank line immediately before and after it.
   Result: 0 violations across all 21 headings.
2. **Fence integrity** — counted all ` ``` ` markers (must be even) and
   confirmed every ` ```mermaid ` block has a matching closing ` ``` `.
   Result: fences balanced, Mermaid block closes correctly.
3. **Bullet/inline-text compression** — searched for list markers glued to
   other content on the same line (a sign of a collapsed list). Result: none
   found; every bullet list renders as a real multi-item list.

**Finding:** the raw file has no structural Markdown defects. The long lines
that remain are exclusively:

- GFM table rows (each row is already on its own line — that's what "proper
  multi-line table" means; a single table _row_ cannot itself span multiple
  raw lines without breaking table parsing), and
- a handful of badge/link lines where the URL itself is long and cannot be
  wrapped without breaking the link.

The widest row (299 characters, the SSRF-residual line in the Security
table) is long because Prettier pads every cell in a column to the width of
that column's longest entry — the same reason the table looks aligned and
readable when rendered. Shortening it would mean cutting the SSRF/TOCTOU
caveat's content, which the brief says not to do.

- Badge wording checked: YES (`runs-local--first_by_default`, confirmed live)
- Security wording checked: YES (exact requested sentence, confirmed live)
- Raw Markdown formatting cleaned: YES (already clean; re-verified, no
  changes needed)
- Tables fixed: N/A — already valid multi-line GFM tables, one row per line
- Code fences fixed: N/A — already open/close on their own lines, fences
  balanced
- Mermaid block fixed: N/A — already opens/closes cleanly and renders
- Links checked: YES — all 7 links from the brief plus the rest of the
  README's links resolve
- Remaining issues: none found in this pass; the only "long lines" are
  spec-required single-line table rows and unwrappable URLs

`git diff -- README.md` and `git diff -- docs/README_UPDATE_REPORT.md` are
both empty for this pass — no README content changed, only this report was
extended.
