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

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

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
