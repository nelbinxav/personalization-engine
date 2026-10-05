#!/usr/bin/env python
"""Append the compact stage 1 prompt as a new active version.

Stage 1 now returns one `facts` list with a `kind` on each item, so the stage 1
prompt that told the model to fill recent_events and tech_signals is out of
date. Prompts are append-only: this adds a version and leaves the old one in
place, so rolling back is activating it again on the Prompts page. The stage 4
prompt is seeded by the api on startup.

    docker compose exec api python scripts/install_compact_prompts.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.defaults import STAGE_1_DOSSIER  # noqa: E402
from app.db import mongo  # noqa: E402
from app.models.prompt import Prompt, Stage  # noqa: E402


async def main() -> None:
    latest = await mongo.prompts().find_one({"stage": int(Stage.dossier)}, sort=[("version", -1)])
    version = (latest or {}).get("version", 0) + 1
    await mongo.prompts().update_many({"stage": int(Stage.dossier)}, {"$set": {"is_active": False}})
    await mongo.prompts().insert_one(
        Prompt(
            stage=Stage.dossier,
            name="Compact dossier prompt",
            body=STAGE_1_DOSSIER,
            version=version,
            is_active=True,
        ).to_mongo()
    )
    print(f"Stage 1 prompt v{version} is now active.")


asyncio.run(main())
