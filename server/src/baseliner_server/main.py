from fastapi import FastAPI

from baseliner_server.api.v1.router import router as v1_router
from baseliner_server.core.config import settings
from baseliner_server.db.init_db import ensure_schema

app = FastAPI(title="Baseliner API", version="0.1.0")


if settings.auto_create_schema or settings.database_url.startswith("sqlite"):
    # SQLite can't run our Alembic migrations, so fall back to metadata-driven
    # creation to keep local smoketests easy.
    ensure_schema()

@app.get("/health")
def health():
    return {"status": "ok"}

app.include_router(v1_router)
