# Installation and operation

This guide installs the system on one computer (a laptop or a small office server) with Docker.
It was followed from a fresh clone at the end of Phase 6; the results are at the end of this
guide.

## 1. What you need

| | Minimum | Recommended |
|---|---|---|
| Operating system | Windows 10/11 (WSL 2), macOS 12+, or 64-bit Linux | Ubuntu 22.04/24.04 server |
| Memory | 4 GB RAM (the stack uses about 1.5 GB) | 8 GB |
| Disk | 5 GB free | 20 GB (room for invoices, photos and backups) |
| Software | [Docker Desktop](https://docs.docker.com/get-docker/) or Docker Engine 24+ with Compose v2, and Git | |
| Network | Internet access for the first build (downloads packages) | |

No GPU is needed. Everything, including OCR and machine learning, runs on the CPU.

## 2. Install

### Step 1: get the code

```bash
git clone <repository URL> smart-inventory
```

```bash
cd smart-inventory
```

### Step 2: create the settings file (`.env`) with random secrets

On Linux or macOS:

```bash
make env
```

Without `make` (for example on Windows): copy `.env.example` to `.env`, then replace the two
`CHANGE_ME` values with long random strings. Python can generate them:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Then open `.env` and set at least:
- `STORE_NAME`, `STORE_ADDRESS`, `STORE_PHONE` and `STORE_KRA_PIN`. These are printed on receipts and reports.
- `FRONTEND_URL`, the address staff will type into the browser (for example `http://192.168.1.20:8080`). It is used for password-reset links.
- `WEB_PORT`, if port 8080 is already taken.

Keep `.env` private. It holds the database password and the token signing key, and it is
never committed to Git.

### Step 3: build and start

```bash
docker compose up -d --build
```

The first build downloads and installs everything, including Tesseract OCR and the Python
and JavaScript packages. Expect 5 to 15 minutes. Later starts take seconds. Check that all
four containers are up:

```bash
docker compose ps
```

`db`, `api` and `web` should show `healthy`, and `worker` `running`. The API applies the
database migrations itself when it starts.

### Step 4: create the first Super Administrator

```bash
docker compose exec api python -m scripts.create_superadmin
```

It asks for a name, username, email and password, and checks the password's strength.

### Step 5: sign in

Open `http://localhost:8080` on the same computer, or the `FRONTEND_URL` from another device
on the network. Sign in, then add your staff under **Administration → Users**. Each person
gets a role (Store Manager, Inventory Officer or Cashier) and must change their temporary
password the first time they sign in.

### Optional: demonstration data

For a presentation or training session only, never on a real store's database:

```bash
docker compose exec -e ENVIRONMENT=development api python -m scripts.seed_demo_users
```

```bash
docker compose exec -e ENVIRONMENT=development api python -m scripts.seed_demo_catalog --history-days 180
```

This creates:
- one demo account per role, all with the password `Demo@2026!`
- 10 demo products and 3 demo suppliers, all marked "(Demo)"
- 180 days of simulated trading, which takes about 2 minutes

The worker then prepares a forecast and an irregularity scan. Sample invoices to try scanning
are in `sample-data/invoices/`. The scripts refuse to run when `ENVIRONMENT=production` is
set without the override shown.

## 3. Everyday operation

| Task | Command |
|---|---|
| Stop the system (data is kept) | `docker compose stop` |
| Start it again | `docker compose start` |
| See what it is doing | `docker compose logs -f --tail=100` |
| Is it healthy? | `docker compose ps` |
| API documentation (interactive) | `http://localhost:8080/api/docs` |

The worker runs these jobs on its own:
- every night: back up, forecast and clean up
- every 3 hours: scan for irregularities
- every 15 minutes: check expiry dates and waiting approvals

## 4. Backups and recovery

**Automatic.** Every night the worker writes a backup into the `storage` volume. Each backup
contains:
- the database, as a `pg_dump` custom-format file
- an archive of the uploaded files (photos, invoices)
- a manifest with checksums

The dump is checked to be readable. The system keeps 7 nightly backups, one per week for 4
weeks, and the last 5 manual ones. A Super Admin sees them under **Administration →
Backups**, can make one now, and can download them.

**Keep a copy elsewhere.** A backup on the same disk does not survive a disk failure or a
theft. Copy backups off the machine regularly, at least weekly: download them from the
Backups page, or run:

```bash
docker compose cp api:/app/storage/backups ./backups-copy
```

**Restore.** This replaces all current data with the backup. Use it after a disaster, or to
move to a new computer (install the system there first, then copy the backup folder into
`storage/backups`):

```bash
make backups
```

```bash
make restore NAME=20261108-020000-daily
```

`make restore` stops the app, checks the backup's checksums, then restores the database in a
single transaction (if anything fails, nothing changes) and the uploaded files. It then
applies any newer migrations and starts the app again. Without `make`, run the four commands
from the `restore:` section of the `Makefile`.

## 5. Updating to a new version

```bash
git pull
```

```bash
docker compose up -d --build
```

Migrations run automatically. Make a manual backup first (Backups page → **Back up now**).

## 6. Using it over a network or the internet

On a shop's local network, staff open `http://<server-ip>:8080`. Set `FRONTEND_URL` to that
address.

Anything reachable from outside the shop **must** use HTTPS. Put a TLS-terminating reverse
proxy in front of the `web` container (Caddy, Traefik or nginx with a certificate, for
example from Let's Encrypt), then in `.env` set:
- `COOKIE_SECURE=true`
- `FRONTEND_URL=https://your.domain`

These proxy set-ups are standard but were not part of this project's tests.

## 7. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `port is already allocated` | Another program uses 8080: set `WEB_PORT` in `.env`, then `docker compose up -d` |
| `Set POSTGRES_PASSWORD in .env` | `.env` is missing or incomplete: step 2 |
| The build fails at `apt-get` or `pip install` | No internet access, or a proxy that Docker does not know about. Configure Docker's proxy settings and retry |
| The page loads but sign-in fails with "Cannot reach the server" | `api` is not healthy yet (it waits for the database and applies migrations): `docker compose logs api` |
| Invoices stay "Waiting to be read" | The worker is not running: `docker compose ps`, `docker compose logs worker` |
| Forecast says "low confidence" | Fewer than 8 weeks of sales recorded for that product; it improves with time |
| Out of memory on a 4 GB machine | Close other programs; the containers have memory limits that total about 1.7 GB |

## 8. Installation check (end of Phase 6)

This guide was followed from a fresh `git clone` of the repository on a clean Docker host.

| Step | Result |
|---|---|
| 2. `make env` | `.env` created; no `CHANGE_ME` left |
| 3. `docker compose up -d --build` | **Not run unchanged:** the build sandbox blocks Debian's package servers, so `apt-get` failed. The backend image was built from an equivalent Ubuntu 24.04 base with the same packages (Tesseract, fonts, PostgreSQL client), the web image with the standard Dockerfile, then `docker compose up -d --no-build`. All four containers became healthy |
| 4. Create the Super Administrator | Done (non-interactively, with `SUPERADMIN_PASSWORD`) |
| 5. Sign in | Home page and sign-in through the web container worked |
| Demo data | 180 days seeded in 2 min 10 s; the worker's forecast and irregularity scan then succeeded |
| `make backup`, `make backups`, `docker compose cp …` | Backup listed (1.0 MB) and copied off the container |
| `make restore NAME=…` | A product added after the backup was gone after the restore; the 10 products and 9,134 sales were back; the app restarted healthy in about 13 seconds |

The one step not verified as written is the image build on a normal internet connection. It
uses the standard `python:3.12-slim` base and Debian packages, and is expected to work.
