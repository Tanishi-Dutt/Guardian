"""Guardian backend. Run from the repo root:  uvicorn backend.app.main:app --reload --port 8000"""
import logging
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config as C
from . import db
from .routers import admin, calls, numbers, signals, stream, tools, web_call

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

if C.SENTRY_DSN:
    sentry_sdk.init(dsn=C.SENTRY_DSN, traces_sample_rate=1.0, send_default_pii=False,
                    _experiments={"enable_logs": True}, environment=C.env("SENTRY_ENV", "dev"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    yield
    await db.close()


app = FastAPI(title="Guardian", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
for r in (calls, tools, stream, numbers, signals, admin, web_call):
    app.include_router(r.router)


@app.get("/health")
async def health():
    return {"ok": True, "db": await db.fetchval("SELECT 1") == 1}
