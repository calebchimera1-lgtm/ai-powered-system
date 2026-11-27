# Third-party software and licences

Smart Inventory is built on the open-source components below. Each keeps its own licence; none
requires the shop to pay or to publish its own data. Generated from the installed packages on
27 November 2026 (`backend/requirements.txt`, `frontend/package.json`).

## Services and containers

| Component | Licence | Notes |
|---|---|---|
| PostgreSQL 16 (database) | PostgreSQL Licence | Official Docker image |
| nginx (web server) | BSD-2-Clause | Official Docker image |
| Tesseract OCR | Apache-2.0 | Installed in the backend image |
| Document archive (optional, `archive` profile) | GPL-3.0 | Unmodified upstream image, run as a separate program; display texts are changed at start-up inside the container. Source: the image's upstream project |
| Redis (archive queue) | BSD-3-Clause (7.2 and earlier) / RSALv2-SSPLv1 or AGPL-3.0 (later) | Used only by the archive |

Fonts: none are shipped; the interface uses the computer's own system fonts. Icons: Lucide (ISC).
Logo: the Smart Inventory logo is the project's own artwork. Sample invoices and demo data are synthetic.

## Python packages (backend)

| Package | Version | Licence |
|---|---|---|
| fastapi | 0.162.5 | MIT |
| uvicorn | 0.34.0 | BSD-3-Clause |
| sqlalchemy | 2.0.36 | MIT |
| alembic | 1.14.0 | MIT |
| psycopg | 3.2.3 | GNU Lesser General Public License v3 (LGPLv3) |
| pydantic | 2.10.4 | MIT |
| pydantic-settings | 2.7.0 | MIT |
| email-validator | 2.2.0 | Unlicense |
| pyjwt | 2.15.1 | MIT |
| argon2-cffi | 23.1.0 | MIT |
| python-multipart | 0.0.33 | Apache-2.0 |
| httpx | 0.28.1 | BSD-3-Clause |
| anthropic | 1.17.0 | MIT |
| pillow | 13.0.0 | MIT-CMU |
| python-barcode | 0.15.1 | MIT |
| numpy | 2.1.3 | BSD License |
| opencv-python-headless | 4.10.0.84 | Apache 2.0 |
| pytesseract | 0.3.13 | Apache License 2.0 |
| pypdfium2 | 5.15.2 | BSD-3-Clause, Apache-2.0, dependency lic |
| pdfplumber | 0.11.10 | MIT License |
| rapidfuzz | 3.10.1 | MIT License |
| reportlab | 4.2.5 | BSD License |
| pandas | 2.2.3 | BSD License |
| scikit-learn | 1.5.2 | BSD License |
| statsmodels | 0.14.4 | BSD License |
| holidays | 0.60 | MIT |
| openpyxl | 3.1.5 | MIT |

## JavaScript packages (frontend)

| Package | Version | Licence |
|---|---|---|
| @hookform/resolvers | 7.0.6 | MIT |
| @tanstack/react-query | 5.62.7 | MIT |
| @zxing/browser | 0.1.5 | MIT |
| @zxing/library | 0.21.3 | MIT |
| axios | 1.21.1 | MIT |
| clsx | 2.1.1 | MIT |
| lucide-react | 0.468.0 | ISC |
| react | 18.3.1 | MIT |
| react-dom | 18.3.1 | MIT |
| react-hook-form | 7.92.0 | MIT |
| react-router-dom | 7.18.5 | MIT |
| recharts | 2.15.0 | MIT |
| zod | 4.6.7 | MIT |
