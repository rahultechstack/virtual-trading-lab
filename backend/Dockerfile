# ---------------------------------------------------------------------------
# FastAPI backend.
#   base  -> shared runtime + dependencies
#   dev   -> hot reload, source bind-mounted by docker-compose
#   prod  -> source baked in, no reload
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies are copied first so image layers cache independently of source.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Run as a non-root user.
RUN useradd --create-home --uid 1000 appuser
USER appuser


FROM base AS dev
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


FROM base AS prod
COPY --chown=appuser:appuser alembic.ini ./
COPY --chown=appuser:appuser alembic ./alembic
COPY --chown=appuser:appuser app ./app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
