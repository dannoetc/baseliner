FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Server uses a src-layout; keep imports working both with and without an editable install.
    PYTHONPATH=/app/server/src

WORKDIR /app/server

# Minimal OS deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy server source
COPY server/ /app/server/

# Install python deps + the server package.
# - requirements.txt provides third-party dependencies
# - editable install makes `baseliner_server` importable (src-layout) and keeps hot-reload sane when volume-mounted
RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install -e .

EXPOSE 8000

CMD ["bash", "-lc", "alembic upgrade head && uvicorn baseliner_server.main:app --host 0.0.0.0 --port 8000"]
