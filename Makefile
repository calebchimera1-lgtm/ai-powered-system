# Shortcuts. Run `make help` for the list.
COMPOSE = docker compose
DEV = docker compose -f docker-compose.yml -f docker-compose.dev.yml

.PHONY: help env up down logs ps superadmin demo-users demo test test-backend test-frontend dev backup backups restore archive archive-token archive-backfill

help:
	@echo "make env           Create .env with random secrets (first time only)"
	@echo "make up            Build and start the whole stack (http://localhost:8080)"
	@echo "make superadmin    Create the first Super Administrator (interactive)"
	@echo "make demo-users    Create one DEMO account per role (not for real stores)"
	@echo "make logs / ps     Follow logs / list containers"
	@echo "make down          Stop the stack (data is kept)"
	@echo "make dev           Start db + api with hot reload on :8000"
	@echo "make demo          Seed 180 days of SYNTHETIC demo trading (after demo-users)"
	@echo "make backup        Back up the database and uploaded files now"
	@echo "make backups       List backups"
	@echo "make restore NAME=<backup>   Restore a backup (stops the app; replaces data)"
	@echo "make db-least-privilege   Move the app onto its own non-superuser database role"
	@echo "make archive       Start the document archive (Paperless-ngx) on :8090"
	@echo "make archive-token Create the API token that files approved invoices there"
	@echo "make archive-backfill  File invoices approved before the archive existed"
	@echo "make test          Run backend and frontend tests"

env:
	@test ! -f .env || (echo ".env already exists; not overwriting" && exit 1)
	@sed -e "s/CHANGE_ME_db_password/$$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')/" \
	     -e "s/CHANGE_ME_app_db_password/$$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')/" \
	     -e "s/CHANGE_ME_paperless_secret/$$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')/" \
	     -e "s/CHANGE_ME_paperless_admin_password/$$(python3 -c 'import secrets;print(secrets.token_urlsafe(18))')/" \
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

demo:
	$(COMPOSE) exec -e ENVIRONMENT=development api python -m scripts.seed_demo_catalog --history-days 180

backup:
	$(COMPOSE) exec api python -c "from app.core.database import SessionLocal; from app.services import backup_service as b; db = SessionLocal(); print(b.create(db, 'manual')['name'])"

backups:
	$(COMPOSE) exec api python -m scripts.restore_backup --list

restore:
	@test -n "$(NAME)" || (echo "Usage: make restore NAME=<backup name from 'make backups'>" && exit 1)
	$(COMPOSE) stop api worker
	$(COMPOSE) run --rm api python -m scripts.restore_backup $(NAME) --yes
	$(COMPOSE) run --rm api alembic upgrade head
	$(COMPOSE) start api worker

# Move an existing installation onto the least-privilege database role. First add
# APP_DB_USER and APP_DB_PASSWORD to .env (see .env.example). Changes ownership only.
db-least-privilege:
	@grep -q '^APP_DB_PASSWORD=..' .env || (echo "Add APP_DB_USER and APP_DB_PASSWORD to .env first" && exit 1)
	$(COMPOSE) up -d db
	$(COMPOSE) exec -T db sh /docker-entrypoint-initdb.d/10-app-role.sh
	$(COMPOSE) up -d --force-recreate api worker

# Document archive (Paperless-ngx). The first start takes a few minutes.
archive:
	@grep -Eq '^PAPERLESS_SECRET_KEY=.{32,}' .env && grep -Eq '^PAPERLESS_ADMIN_PASSWORD=.{12,}' .env \
	  && ! grep -Eq '^PAPERLESS_(SECRET_KEY|ADMIN_PASSWORD)=CHANGE_ME' .env \
	  || (echo "Set PAPERLESS_SECRET_KEY (32+ chars) and PAPERLESS_ADMIN_PASSWORD (12+ chars) in .env first" && exit 1)
	mkdir -p archive-inbox
	ARCHIVE_UID=$$(id -u) ARCHIVE_GID=$$(id -g) $(COMPOSE) --profile archive up -d archive-redis archive

# Prints a token for the archive admin account. Put it in .env as PAPERLESS_TOKEN,
# then run `docker compose up -d api worker`.
archive-token:
	@$(COMPOSE) --profile archive exec -T archive sh -c 'cd /usr/src/paperless/src && python3 manage.py drf_create_token "$$PAPERLESS_ADMIN_USER"'

archive-backfill:
	$(COMPOSE) exec api python -m scripts.archive_invoices

dev:
	$(DEV) up --build db api worker

test: test-backend test-frontend

test-backend:
	cd backend && python -m pytest

test-frontend:
	cd frontend && npm test
