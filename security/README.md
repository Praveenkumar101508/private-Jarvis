# Security — supply-chain scanning

We use [Perplexity Bumblebee](https://github.com/perplexityai/bumblebee)
(Apache-2.0) to check this repository and the developer environment for exposure
to known software supply-chain compromises.

Bumblebee is **read-only**: it inventories on-disk package metadata (npm, pnpm,
Yarn, Bun, PyPI, Go modules, RubyGems, Composer, MCP configs, editor/browser
extensions) and flags exact `(ecosystem, name, version)` matches against threat
catalogs. It **never executes install scripts and never invokes package
managers**, so running it cannot trigger a scan-time compromise. Keep it that way.

## Install (once)

Requires Go 1.25+ (the module declares `go >= 1.25`; the Go toolchain will
auto-fetch it). The binary lands in `$(go env GOPATH)/bin`, which should be on
your `PATH`.

```
go install github.com/perplexityai/bumblebee/cmd/bumblebee@latest
bumblebee selftest        # expect: selftest OK
```

## Run

```
cd supracloud-jarvis
make security
```

`make security` runs two read-only passes and writes NDJSON to `security/`:

| File | What it is |
| --- | --- |
| `ira-project-scan.ndjson` | Project-profile inventory of installed package metadata under the repo. |
| `ira-exposure.ndjson` | Deep exposure check vs the vendored compromise catalogs (`record_type=finding` on any match). |

The target exits non-zero if any exposure finding is detected.

### Optional: baseline the dev machine

```
bumblebee scan --profile baseline > security/dev-baseline.ndjson
bumblebee scan --profile baseline \
  --exposure-catalog ../third_party/bumblebee/threat_intel --findings-only \
  > security/dev-exposure.ndjson
```

`dev-baseline.ndjson` is machine-specific inventory and is git-ignored — run it
on the actual dev/Shadow box (not an ephemeral CI container) for it to be
meaningful.

## Catalogs

Exposure catalogs are vendored under `third_party/bumblebee/threat_intel/`
(Bumblebee v0.1.1) with the upstream Apache-2.0 LICENSE. They currently cover:
shai-hulud (npm), gemstuffer (RubyGems), node-ipc credential stealer, the
nx-console VS Code compromise, and the shopsprint decimal typosquat. They are
point-in-time intel — refresh periodically (see `third_party/bumblebee/NOTICE.md`).

## Baseline result (2026-06-16)

- Repo project/deep scan: **0 package records** (fresh checkout, no installed
  dependencies on disk) → **0 exposure findings**.
- Dev environment baseline: **515 packages** (355 npm, 122 go, 37 pypi, 1 mcp) →
  **0 exposure findings** against all catalogs.

No compromised package/version matches were found; nothing required remediation.
