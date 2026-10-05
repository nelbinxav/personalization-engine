#!/usr/bin/env python
"""Show or change the personalization switches, which the Settings page does
not have controls for yet. Changes apply to the next row; no restart.

    docker compose exec api python scripts/set_ai_config.py                 # show
    docker compose exec api python scripts/set_ai_config.py --mode personalized_line --compact off
    docker compose exec api python scripts/set_ai_config.py --compact on --terms-file terms.txt
    docker compose exec api python scripts/set_ai_config.py --mode full_message --compact off   # roll back

--terms takes a comma-separated list; --terms-file one term per line.
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import settings_store  # noqa: E402
from app.models.settings import OutputMode  # noqa: E402


def show(ai) -> None:
    print(f"personalization_output_mode = {ai.personalization_output_mode.value}")
    print(f"compact_research            = {ai.compact_research}")
    print(f"compact_chars_per_source    = {ai.compact_chars_per_source}")
    print(f"relevance_terms             = {len(ai.relevance_terms)} terms {ai.relevance_terms[:6]}...")
    print(f"combined_final              = {ai.combined_final}")


async def main(args: argparse.Namespace) -> None:
    settings = await settings_store.load()
    changed = False
    if args.mode:
        settings.ai.personalization_output_mode = OutputMode(args.mode)
        changed = True
    if args.compact:
        settings.ai.compact_research = args.compact == "on"
        changed = True
    terms = None
    if args.terms is not None:
        terms = [t.strip() for t in args.terms.split(",")]
    if args.terms_file:
        terms = [t.strip() for t in Path(args.terms_file).read_text().splitlines()]
    if terms is not None:
        settings.ai.relevance_terms = [t for t in terms if t]
        changed = True
    if changed:
        await settings_store.save(settings)
        print("Saved.")
    show(settings.ai)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=[m.value for m in OutputMode])
    parser.add_argument("--compact", choices=["on", "off"])
    parser.add_argument("--terms")
    parser.add_argument("--terms-file")
    asyncio.run(main(parser.parse_args()))
