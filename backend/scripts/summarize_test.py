#!/usr/bin/env python
"""Summarise a personalization test batch from the stored per-row metrics.

Read-only. Compares personalized_line with compact research OFF (A) and ON (B):

    docker compose exec api python scripts/summarize_test.py
    docker compose exec api python scripts/summarize_test.py --upload <id> --upload <id>
    docker compose exec api python scripts/summarize_test.py --since 2026-10-06T00:00:00

Rows only appear once they were personalized with line mode or compact research
on (that is when the metrics are written). Nothing here prints research text,
lines, names or emails.
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.measure import by_config, render  # noqa: E402
from app.db import mongo  # noqa: E402


async def main(uploads: list[str], since: str | None) -> None:
    query: dict = {"personalization.metrics.output_mode": {"$exists": True}}
    if uploads:
        query["upload_id"] = {"$in": uploads}
    if since:
        query["personalization.generated_at"] = {"$gte": since}
    rows = []
    cursor = mongo.prospects().find(query, {"personalization.metrics": 1})
    async for doc in cursor:
        rows.append(doc["personalization"]["metrics"])
    if not rows:
        print("No rows with metrics found.")
        return
    print(render(by_config(rows)))
    print(f"\n{len(rows)} rows with metrics. The deciding number is tokens per successful line.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--upload", action="append", default=[], help="limit to an upload id (repeatable)")
    parser.add_argument("--since", help="only rows personalized at or after this ISO time")
    args = parser.parse_args()
    asyncio.run(main(args.upload, args.since))
