# agency-agents — third-party content

- **Project:** agency-agents — a collection of specialised Claude Code sub-agents
- **Upstream:** https://github.com/msitarzewski/agency-agents
- **License:** MIT (see `LICENSE` in this directory — © 2025 AgentLand Contributors)

## What is used here

Four agent definition files were copied into `.claude/agents/` to speed up IRA
**development** (they are dev-time sub-agents, not part of IRA's runtime). Each
installed file carries an MIT provenance header. They are used essentially
unmodified — only the frontmatter `name` was slugified so Claude Code can invoke
them as a subagent type.

| Brief role     | Installed as                    | Upstream file                          |
| -------------- | ------------------------------- | -------------------------------------- |
| backend        | `.claude/agents/backend-architect.md` | `engineering/engineering-backend-architect.md` |
| frontend       | `.claude/agents/frontend-developer.md` | `engineering/engineering-frontend-developer.md` |
| code-reviewer  | `.claude/agents/code-reviewer.md`      | `engineering/engineering-code-reviewer.md`     |
| test-engineer  | `.claude/agents/api-tester.md`         | `testing/testing-api-tester.md`        |

**Note on "test-engineer":** agency-agents has no agent named exactly
"test-engineer". The closest fit for IRA's FastAPI + pytest codebase is
**API Tester** (`testing/testing-api-tester.md`), which writes and runs functional/
security/performance API tests — so it was installed under `api-tester.md`.

The MIT license requires the copyright + permission notice be retained; `LICENSE`
here satisfies that for the copied files.
