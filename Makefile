# Shortcuts. Run `make help` for the list.
COMPOSE = docker compose
DEV = docker compose -f docker-compose.yml -f docker-compose.dev.yml

.PHONY: help env up down logs ps superadmin demo-users test test-backend test-frontend dev

help:
	@echo "make env           Create .env with random secrets (first time only)"
	@echo "make up            Build and start the whole stack (http://localhost:8080)"
	@echo "make superadmin    Create the first Super Administrator (interactive)"
	@echo "make demo-users    Create one DEMO account per role (not for real stores)"
	@echo "make logs / ps     Follow logs / list containers"
	@echo "make down          Stop the stack (data is kept)"
	@echo "make dev           Start db + api with hot reload on :8000"
	@echo "make test          Run backend and frontend tests"

env:
	@test ! -f .env || (echo ".env already exists; not overwriting" && exit 1)
	@sed -e "s/CHANGE_ME_db_password/$$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')/" \
	     -e "s/CHANGE_ME_generate_a_long_random_value/$$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')/" \
	     .env.example > .env
	@echo "Created .env with random secrets."

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

superadmin:
	$(COMPOSE) exec api python -m scripts.create_superadmin

demo-users:
	$(COMPOSE) exec -e ENVIRONMENT=development api python -m scripts.seed_demo_users

dev:
	$(DEV) up --build db api worker

test: test-backend test-frontend

test-backend:
	cd backend && python -m pytest

test-frontend:
	cd frontend && npm test
