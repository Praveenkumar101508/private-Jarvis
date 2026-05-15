.PHONY: help up down logs build clean setup pull-supracloud

help:
	@echo ""
	@echo "IRA — Intelligent Responsive Assistant"
	@echo "======================================"
	@echo ""
	@echo "  make setup          Copy .env.example → .env (first-time setup)"
	@echo "  make up             Start all services (docker compose up -d)"
	@echo "  make down           Stop all services"
	@echo "  make logs           Tail all logs"
	@echo "  make build          Rebuild all Docker images"
	@echo "  make clean          Remove containers and volumes (destructive!)"
	@echo "  make pull-supracloud  Import supracloud website"
	@echo ""

setup:
	@[ -f .env ] || cp .env.example .env
	@echo "✓ .env created. Edit it with your API keys before running 'make up'."

up:
	docker compose up -d
	@echo "✓ IRA is running!"
	@echo "  Frontend:  http://localhost:3000"
	@echo "  API:       http://localhost:8000"
	@echo "  API Docs:  http://localhost:8000/docs"
	@echo "  SupraCloud: http://localhost:3001"

down:
	docker compose down

logs:
	docker compose logs -f

build:
	docker compose build --no-cache

clean:
	docker compose down -v --remove-orphans

pull-supracloud:
	git remote add supracloud https://github.com/Praveenkumar101508/supracloud.git 2>/dev/null || true
	git fetch supracloud
	git read-tree --prefix=supracloud-website/ -u supracloud/main
	git commit -m "feat: merge supracloud website from upstream"
	git remote remove supracloud
