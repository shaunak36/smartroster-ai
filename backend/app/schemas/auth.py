from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.auth import UserRole


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class BootstrapAdminRequest(BaseModel):
    bootstrap_token: str = Field(min_length=1, max_length=512)
    organization_name: str = Field(min_length=1, max_length=160)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=12, max_length=256)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    is_active: bool
    created_at: datetime


class MembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: int
    user_id: int
    role: UserRole
    is_active: bool
