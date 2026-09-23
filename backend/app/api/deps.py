from datetime import timedelta

from fastapi import Cookie, Depends, HTTPException, Response, status

from app.core.config import get_settings
from app.core.security import new_session_token
from app.db import mongo
from app.models.common import utcnow
from app.models.operator import Operator, Session

SESSION_COOKIE = "pe_session"


async def create_session(response: Response, operator: Operator) -> str:
    env = get_settings()
    token = new_session_token()
    expires_at = utcnow() + timedelta(hours=env.session_ttl_hours)

    await mongo.sessions().insert_one(
        Session(token=token, operator_id=operator.id, expires_at=expires_at).to_mongo()
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=env.cookie_secure,
        samesite="lax",
        max_age=env.session_ttl_hours * 3600,
        path="/",
    )
    return token


async def destroy_session(response: Response, token: str | None) -> None:
    if token:
        await mongo.sessions().delete_one({"token": token})
    response.delete_cookie(SESSION_COOKIE, path="/")


async def current_operator(
    pe_session: str | None = Cookie(default=None),
) -> Operator:
    if not pe_session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")

    session = await mongo.sessions().find_one({"token": pe_session})
    if not session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")

    # Mongo's TTL reaper runs about once a minute, so check explicitly too.
    if session["expires_at"] <= utcnow():
        await mongo.sessions().delete_one({"token": pe_session})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")

    doc = await mongo.operators().find_one({"_id": session["operator_id"]})
    if not doc or not doc.get("is_active", True):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is not active")

    return Operator.model_validate(doc)


CurrentOperator = Depends(current_operator)
