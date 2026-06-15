.PHONY: secrets-encrypt secrets-decrypt secrets-edit secrets-view \
        up down logs up-secure test test-unit test-coverage

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
