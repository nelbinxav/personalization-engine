from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status

from app.api.deps import create_session, current_operator, destroy_session
from app.core.security import verify_password
from app.db import mongo
from app.models.operator import LoginRequest, Operator, OperatorOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=OperatorOut)
async def login(payload: LoginRequest, response: Response) -> OperatorOut:
    doc = await mongo.operators().find_one({"email": payload.email.lower()})
    # Same message either way -- don't reveal which accounts exist.
    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not doc:
        raise invalid

    operator = Operator.model_validate(doc)
    if not operator.is_active or not verify_password(payload.password, operator.password_hash):
        raise invalid

    await create_session(response, operator)
    return OperatorOut(id=operator.id, email=operator.email, name=operator.name)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, pe_session: str | None = Cookie(default=None)) -> None:
    await destroy_session(response, pe_session)


@router.get("/me", response_model=OperatorOut)
async def me(operator: Operator = Depends(current_operator)) -> OperatorOut:
    return OperatorOut(id=operator.id, email=operator.email, name=operator.name)
