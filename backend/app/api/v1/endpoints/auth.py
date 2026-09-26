import logging

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status

from app.api.deps import create_session, current_operator, destroy_session
from app.core.security import verify_password
from app.db import mongo
from app.models.operator import LoginRequest, Operator, OperatorOut
from app.worker.bookkeeping import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Failed-login throttle, per account. Per account rather than per IP because
# behind a tunnel or proxy every request arrives from the same address. The
# cost is that someone can lock a known account out for the window.
MAX_FAILURES = 10
FAILURE_WINDOW_SECONDS = 15 * 60


def _failure_key(email: str) -> str:
    return f"login_failures:{email}"


async def _failures(email: str) -> int:
    redis = await get_redis()
    try:
        return int(await redis.get(_failure_key(email)) or 0)
    finally:
        await redis.close()


async def _record_failure(email: str) -> None:
    redis = await get_redis()
    try:
        key = _failure_key(email)
        if await redis.incr(key) == 1:
            await redis.expire(key, FAILURE_WINDOW_SECONDS)
    finally:
        await redis.close()


async def _clear_failures(email: str) -> None:
    redis = await get_redis()
    try:
        await redis.delete(_failure_key(email))
    finally:
        await redis.close()


@router.post("/login", response_model=OperatorOut)
async def login(payload: LoginRequest, response: Response) -> OperatorOut:
    email = payload.email.lower()

    # Fail open if Redis is down: the throttle guards against guessing, it
    # must not become the reason nobody can sign in.
    try:
        locked = await _failures(email) >= MAX_FAILURES
    except Exception:
        logger.exception("Login throttle unavailable")
        locked = False
    if locked:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed sign-in attempts. Try again in 15 minutes.",
        )

    doc = await mongo.operators().find_one({"email": email})
    # Same message either way -- don't reveal which accounts exist.
    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    operator = Operator.model_validate(doc) if doc else None
    if (
        not operator
        or not operator.is_active
        or not verify_password(payload.password, operator.password_hash)
    ):
        try:
            await _record_failure(email)
        except Exception:
            logger.exception("Login throttle unavailable")
        raise invalid

    try:
        await _clear_failures(email)
    except Exception:
        logger.exception("Login throttle unavailable")
    await create_session(response, operator)
    return OperatorOut(id=operator.id, email=operator.email, name=operator.name)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, pe_session: str | None = Cookie(default=None)) -> None:
    await destroy_session(response, pe_session)


@router.get("/me", response_model=OperatorOut)
async def me(operator: Operator = Depends(current_operator)) -> OperatorOut:
    return OperatorOut(id=operator.id, email=operator.email, name=operator.name)
