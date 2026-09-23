#!/usr/bin/env python
"""Seed an operator account. There is no self-signup.

    python scripts/create_operator.py ops@bighammer.ai
    docker compose exec api python scripts/create_operator.py ops@bighammer.ai
"""
import argparse
import asyncio
import getpass
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.security import hash_password  # noqa: E402
from app.db import mongo  # noqa: E402
from app.db.init_db import initialize_database  # noqa: E402
from app.models.operator import Operator  # noqa: E402


async def main(email: str, name: str | None, password: str | None) -> int:
    await initialize_database()

    email = email.strip().lower()
    existing = await mongo.operators().find_one({"email": email})

    generated = False
    if not password:
        if sys.stdin.isatty():
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Confirm: "):
                print("Passwords did not match.", file=sys.stderr)
                return 1
        else:
            password = secrets.token_urlsafe(16)
            generated = True

    if len(password) < 10:
        print("Password must be at least 10 characters.", file=sys.stderr)
        return 1

    password_hash = hash_password(password)

    if existing:
        await mongo.operators().update_one(
            {"_id": existing["_id"]},
            {"$set": {"password_hash": password_hash, "is_active": True, "name": name}},
        )
        print(f"Updated password for {email}")
    else:
        await mongo.operators().insert_one(
            Operator(email=email, password_hash=password_hash, name=name).to_mongo()
        )
        print(f"Created operator {email}")

    if generated:
        print(f"Generated password: {password}")

    await mongo.close_client()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create or update an operator account")
    parser.add_argument("email")
    parser.add_argument("--name", default=None)
    parser.add_argument(
        "--password",
        default=None,
        help="Read from a prompt when omitted; generated when not on a TTY.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.email, args.name, args.password)))
