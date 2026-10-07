import logging

from pymongo import ASCENDING, DESCENDING

from app.db import mongo

logger = logging.getLogger(__name__)


async def initialize_database() -> None:
    """Create indexes. Safe to run on every startup."""
    await mongo.operators().create_index([("email", ASCENDING)], unique=True)

    # TTL index: mongo reaps expired sessions for us.
    await mongo.sessions().create_index([("token", ASCENDING)], unique=True)
    await mongo.sessions().create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)

    await mongo.uploads().create_index([("created_at", DESCENDING)])

    # The hot path: "give me page N of rows for this upload, in sheet order".
    await mongo.prospects().create_index(
        [("upload_id", ASCENDING), ("row_index", ASCENDING)], unique=True
    )
    await mongo.prospects().create_index([("upload_id", ASCENDING), ("scrape_status", ASCENDING)])
    await mongo.prospects().create_index(
        [("upload_id", ASCENDING), ("personalize_status", ASCENDING)]
    )

    await mongo.jobs().create_index([("created_at", DESCENDING)])
    await mongo.jobs().create_index([("upload_id", ASCENDING), ("created_at", DESCENDING)])
    await mongo.jobs().create_index([("status", ASCENDING)])

    # Prompts and templates are append-only; (stage, version) / (channel, version)
    # identify a revision and `is_active` marks the one in use.
    await mongo.prompts().create_index([("stage", ASCENDING), ("version", DESCENDING)])
    await mongo.templates().create_index([("channel", ASCENDING), ("version", DESCENDING)])
    await mongo.agents().create_index([("lineage_id", ASCENDING), ("version", DESCENDING)])

    # Scrape response cache, expired by mongo via a per-document expires_at.
    await mongo.source_cache().create_index(
        [("source", ASCENDING), ("cache_key", ASCENDING)], unique=True
    )
    await mongo.source_cache().create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)

    # Parsed-but-uncommitted uploads awaiting column mapping.
    await mongo.staging().create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)

    # Per-day provider counters (the LinkedIn daily cap), reaped after a few days.
    await mongo.counters().create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)

    logger.info("Database indexes ensured")
