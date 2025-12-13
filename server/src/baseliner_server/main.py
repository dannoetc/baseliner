from fastapi import FastAPI
from baseliner_server.api.v1.router import router as v1_router

app = FastAPI(title="Baseliner API", version="0.1.0")

@app.get("/health")
def health():
    return {"status": "ok"}

app.include_router(v1_router)
