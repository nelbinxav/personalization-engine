from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.common import Doc, utcnow


class Operator(Doc):
    email: str
    password_hash: str
    name: str | None = None
    is_active: bool = True


class Session(Doc):
    token: str
    operator_id: str
    expires_at: datetime


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class OperatorOut(BaseModel):
    id: str
    email: str
    name: str | None = None
