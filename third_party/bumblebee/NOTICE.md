# Bumblebee — third-party component

- **Project:** Perplexity Bumblebee — read-only developer endpoint supply-chain scanner
- **Upstream:** https://github.com/perplexityai/bumblebee
- **Version vendored:** v0.1.1
- **License:** Apache License 2.0 (see `LICENSE` in this directory)

## What is vendored here and why

Only the **exposure catalogs** under `threat_intel/` are vendored, so the
`make security` exposure check stays reproducible after an ephemeral build
container (whose Go module cache is discarded) is gone. We do **not** vendor or
redistribute Bumblebee's source code — the binary is obtained at use time via:

```
go install github.com/perplexityai/bumblebee/cmd/bumblebee@latest
```

The `LICENSE` file is retained as required by the Apache-2.0 license because the
`threat_intel/*.json` catalogs are copied from the upstream repository.

## How we use it

Bumblebee is invoked **read-only**: it inventories on-disk package metadata and
flags exact `(ecosystem, name, version)` matches against the catalogs. It never
executes install scripts and never invokes package managers. See
`security/README.md` for the scan commands and `make security`.

## Updating the catalogs

Re-copy `threat_intel/*.json` from a newer tagged Bumblebee release and bump the
version recorded above. The catalogs are point-in-time threat intelligence and
will go stale; refresh them periodically.
