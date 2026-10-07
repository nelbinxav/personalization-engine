from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import get_settings

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(get_settings().mongodb_url, tz_aware=True)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    return get_client()[get_settings().mongodb_db]


async def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


# Collection accessors -- import these rather than hardcoding names at call sites.
def operators():
    return get_db()["operators"]


def sessions():
    return get_db()["sessions"]


def uploads():
    return get_db()["uploads"]


def prospects():
    return get_db()["prospects"]


def jobs():
    return get_db()["jobs"]


def prompts():
    return get_db()["prompts"]


def templates():
    return get_db()["templates"]


def app_settings():
    return get_db()["settings"]


def source_cache():
    return get_db()["source_cache"]


def staging():
    return get_db()["staging"]


def counters():
    return get_db()["counters"]


def agents():
    return get_db()["agents"]
