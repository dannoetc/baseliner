from fastapi import FastAPI

from baseliner_server.api.v1.router import router as v1_router
from baseliner_server.middleware.correlation import CorrelationIdMiddleware

app = FastAPI(title="Baseliner API", version="0.1.0")

# Propagate/echo X-Correlation-ID so operators can trace agent logs <-> server logs.
app.add_middleware(CorrelationIdMiddleware, log_requests=True)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(v1_router)
