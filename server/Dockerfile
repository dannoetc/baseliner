FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/server

# Minimal OS deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

# Copy server source
COPY server/ /app/server/

# Install python deps + server package (editable for hot reload when volume-mounted)
RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt

EXPOSE 8000

CMD ["bash", "-lc", "alembic upgrade head && uvicorn baseliner_server.main:app --host 0.0.0.0 --port 8000"]
