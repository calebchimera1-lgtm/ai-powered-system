# Backend image: FastAPI API and background worker share this image.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Tesseract OCR (+ English data), fonts for the synthetic invoice generator, and the
# one shared library OpenCV's headless build needs. ~60 MB in total.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
       fonts-dejavu-core fonts-liberation libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini pyproject.toml ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Run as an unprivileged user; storage is the only writable location.
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/storage \
    && chown -R appuser:appuser /app/storage
USER appuser

EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["api"]
