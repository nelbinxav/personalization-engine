"""FastAPI entrypoint.

Run locally with:  uvicorn app.main:app --reload
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.api_router import api_router
from app.core.config import get_settings
from app.db import mongo
from app.db.init_db import initialize_database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    await initialize_database()
    await seed_defaults()
    logger.info("API ready")
    yield
    await mongo.close_client()


async def seed_defaults() -> None:
    """Install the starter prompts and templates on a fresh database.

    Without these the personalization tab is an empty form and the operator has
    to invent three prompts before seeing anything work.
    """
    from app.ai.defaults import ensure_defaults

    await ensure_defaults()


app = FastAPI(title="Personalization Engine", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "personalization-engine-api"}
