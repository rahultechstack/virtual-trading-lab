# ---------------------------------------------------------------------------
# FastAPI backend.
#   base  -> runtime + application dependencies
#   dev   -> adds test tooling, hot reload, source bind-mounted by compose
#   prod  -> source baked in, no reload, no test tooling
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

RUN useradd --create-home --uid 1000 appuser


FROM base AS dev
# Test tooling lives only in the dev image.
COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
USER appuser
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


FROM base AS prod
COPY --chown=appuser:appuser alembic.ini ./
COPY --chown=appuser:appuser alembic ./alembic
COPY --chown=appuser:appuser app ./app
USER appuser
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
