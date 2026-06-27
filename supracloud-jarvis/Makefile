.PHONY: secrets-encrypt secrets-decrypt secrets-edit secrets-view \
        up down logs up-secure test test-unit test-coverage security

# ── Secrets management (sops + age) ──────────────────────────────────────────

# Encrypt plaintext .env → .env.enc
secrets-encrypt:
	@echo "Encrypting .env → .env.enc..."
	sops -e .env > .env.enc
	@echo "✅ Done. Commit .env.enc — never commit .env"

# Decrypt .env.enc → .env
secrets-decrypt:
	@echo "Decrypting .env.enc → .env..."
	sops -d .env.enc > .env
	chmod 600 .env
	@echo "✅ Done."

# Edit encrypted secrets in-place
secrets-edit:
	sops .env.enc

# View decrypted secrets without writing to disk
secrets-view:
	sops -d .env.enc

# ── Docker helpers ────────────────────────────────────────────────────────────

# IRA runs NATIVE on Windows (Shadow PC) — there is no docker-compose.yml.
# Bring up the full stack (Postgres, Memurai, Ollama, Cortex gateway, SearXNG/
# Crawl4AI, ira-api, frontend) with the native launcher:
up:
	@echo "IRA runs native on Windows — start the stack with:"
	@echo "    pwsh -File ./start-ira.ps1"
	@echo "(see start-ira.ps1; the old 'docker compose up' path is retired — no compose file)"

down:
	@echo "Stop the native services from the Services panel (Postgres/Memurai) or"
	@echo "close the Ollama/Cortex/uvicorn/next windows started by start-ira.ps1."

logs:
	@echo "Native stack: check each service's own console window / Windows Event Viewer."

# Start with decrypted secrets piped directly to docker compose
up-secure:
	sops -d .env.enc | docker compose --env-file /dev/stdin up -d

# ── Security: supply-chain scan (Perplexity Bumblebee, read-only) ─────────────

# Bumblebee inventories on-disk package metadata and flags exact matches against
# the vendored compromise catalogs. It is READ-ONLY: it never runs install
# scripts and never invokes package managers — keep it that way.
# Install once: go install github.com/perplexityai/bumblebee/cmd/bumblebee@latest
REPO_ROOT := $(CURDIR)/..
CATALOGS  := $(REPO_ROOT)/third_party/bumblebee/threat_intel
BUMBLEBEE ?= bumblebee

security:
	@command -v $(BUMBLEBEE) >/dev/null 2>&1 || { \
	  echo "bumblebee not found. Install: go install github.com/perplexityai/bumblebee/cmd/bumblebee@latest"; \
	  echo "(then ensure $$(go env GOPATH)/bin is on PATH, or run: make security BUMBLEBEE=\$$(go env GOPATH)/bin/bumblebee)"; \
	  exit 1; }
	@mkdir -p $(REPO_ROOT)/security
	@echo "→ Bumblebee project inventory scan…"
	$(BUMBLEBEE) scan --profile project --root $(REPO_ROOT) > $(REPO_ROOT)/security/ira-project-scan.ndjson
	@echo "→ Bumblebee exposure check vs vendored compromise catalogs…"
	$(BUMBLEBEE) scan --profile deep --root $(REPO_ROOT) --exposure-catalog $(CATALOGS) --findings-only > $(REPO_ROOT)/security/ira-exposure.ndjson
	@findings=$$(grep -c '"record_type":"finding"' $(REPO_ROOT)/security/ira-exposure.ndjson 2>/dev/null || true); \
	 echo "exposure findings: $$findings"; \
	 if [ "$$findings" != "0" ]; then echo "⚠️  exposure findings — review security/ira-exposure.ndjson"; exit 1; fi
	@echo "✅ security scan complete (read-only) — NDJSON written under security/"

# ── Tests ─────────────────────────────────────────────────────────────────────

# Run all tests in Docker
test:
	bash scripts/test.sh

# Run quick unit tests locally (no Docker)
test-unit:
	cd ira && python -m pytest tests/ -v -k "not integration" --tb=short

# Run with coverage
test-coverage:
	cd ira && python -m pytest tests/ --cov=. --cov-report=html --cov-report=term-missing
	xdg-open ira/htmlcov/index.html 2>/dev/null || open ira/htmlcov/index.html 2>/dev/null || true
