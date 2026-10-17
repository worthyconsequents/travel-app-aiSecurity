import os

from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok", "service": os.getenv("SERVICE", "api"), "mode": "mock"}
