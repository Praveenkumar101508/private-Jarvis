# SupraCloud IRA — Branch Cleanup Report

_Phase 8. Target end state: only **`supracloud_ira`** and **`ira`** remain._

## Verification method

For every remote branch: `git rev-list --count origin/supracloud_ira..origin/<branch>`
(unique commits not contained in `supracloud_ira`) plus an open-PR check via the GitHub
API (**zero open PRs exist on the repository**). Verified after `git fetch --all --prune`
against the live remote; the full test suite is green on the consolidated history.

## Branch-by-branch decision table

| Branch | Tip | Unique commits vs `supracloud_ira` | Assessment | Recommendation |
| --- | --- | --- | --- | --- |
| `supracloud_ira` | `4869034` | — (baseline, 96 commits) | default/integration branch; all history consolidated here | **KEEP — never delete** |
| `ira` | `8ad11f8` | 1 — "ira: legacy codebase archive (pre-restructure)" | intentional frozen archive of the pre-restructure codebase; that commit must NOT be merged into `supracloud_ira` (it would resurrect the old tree) | **KEEP — never delete, never merge** |
| `v2-portable-demo` | `5675a39` | **0** | fully merged | **DELETE** |
| `claude/ira-answer-quality-mtg7r2` | `3361968` | **0** | fully merged (PR history) | **DELETE** |
| `claude/ira-model-routing-audit-tx5n4i` | `9521efd` | **0** | fully merged | **DELETE** |
| `claude/ira-model-routing-improvements-pftx4e` | `447ea56` | **0** | fully merged | **DELETE** |
| `claude/ira-smart-model-selection-yo0ws6` | `331db2f` | **0** | fully merged | **DELETE** |
| `claude/update-ira-readme-27x9rj` | `2912299` | **0** | fully merged | **DELETE** |
| `claude/v1-v2-gate-sequence-6ee58p` | `5675a39` | **0** | fully merged (same tip as v2-portable-demo) | **DELETE** |
| `claude/supracloud-ira-release-audit-lop54z` | (this work) | this release-prep pass | working branch for the publication PR | delete **after** its PR merges into `supracloud_ira` |

No branch required merging or cherry-picking: every deletion candidate has **zero unique
commits**, so no work is lost and no backup branch is strictly required (each deleted
branch's content is byte-identical history already inside `supracloud_ira`).

## Deletion attempt from this environment

`git push origin --delete <branch>` was executed for all seven candidates and was
**silently rejected by this environment's git proxy** (pushes here are restricted to the
session's working branch; `git ls-remote` confirmed all branches still exist). Deletion
must be done manually.

## Exact manual commands (run from any normal clone with push rights)

```bash
git fetch --all --prune

# 1. (Optional but recommended) safety tags — lets you restore any branch instantly
git tag backup/v2-portable-demo                      origin/v2-portable-demo
git tag backup/claude-ira-answer-quality             origin/claude/ira-answer-quality-mtg7r2
git tag backup/claude-ira-model-routing-audit        origin/claude/ira-model-routing-audit-tx5n4i
git tag backup/claude-ira-model-routing-improvements origin/claude/ira-model-routing-improvements-pftx4e
git tag backup/claude-ira-smart-model-selection      origin/claude/ira-smart-model-selection-yo0ws6
git tag backup/claude-update-ira-readme              origin/claude/update-ira-readme-27x9rj
git tag backup/claude-v1-v2-gate-sequence            origin/claude/v1-v2-gate-sequence-6ee58p
git push origin --tags

# 2. Re-verify nothing unique (each must print 0)
for b in v2-portable-demo claude/ira-answer-quality-mtg7r2 \
         claude/ira-model-routing-audit-tx5n4i claude/ira-model-routing-improvements-pftx4e \
         claude/ira-smart-model-selection-yo0ws6 claude/update-ira-readme-27x9rj \
         claude/v1-v2-gate-sequence-6ee58p; do
  echo "$b: $(git rev-list --count origin/supracloud_ira..origin/$b) unique"
done

# 3. Delete
git push origin --delete v2-portable-demo
git push origin --delete claude/ira-answer-quality-mtg7r2
git push origin --delete claude/ira-model-routing-audit-tx5n4i
git push origin --delete claude/ira-model-routing-improvements-pftx4e
git push origin --delete claude/ira-smart-model-selection-yo0ws6
git push origin --delete claude/update-ira-readme-27x9rj
git push origin --delete claude/v1-v2-gate-sequence-6ee58p

# 4. After the release-prep PR merges, also delete its working branch:
git push origin --delete claude/supracloud-ira-release-audit-lop54z

git fetch --all --prune   # confirm: only supracloud_ira and ira remain
```

Restore recipe (if ever needed): `git push origin <tip-sha>:refs/heads/<branch>` using the
tip SHAs recorded in the table above, or the backup tags from step 1.

## Safety rules honored

- `supracloud_ira` and `ira` are never touched.
- No force-pushes anywhere.
- Nothing recommended for deletion carries unique commits; tip SHAs are recorded above and
  optional backup tags are provided anyway.
- Verification (full test suite + build) ran on the consolidated history before any
  deletion was attempted.
