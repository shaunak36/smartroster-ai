from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import ExpiredSignatureError, InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import OrganizationMembership, User, UserRole

password_hash = PasswordHash.recommended()
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class OrganizationContext:
    user: User
    organization_id: int
    role: UserRole


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    return password_hash.verify(password, stored_hash)


def _secret(settings: Settings) -> str:
    if not settings.auth_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        )
    return settings.auth_secret


def create_access_token(user: User, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "iss": settings.auth_issuer,
        "aud": settings.auth_audience,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, _secret(settings), algorithm="HS256")


def authenticate_user(
    session: Session,
    email: str,
    password: str,
) -> User | None:
    user = session.scalar(
        select(User)
        .options(
            selectinload(User.memberships).selectinload(
                OrganizationMembership.organization
            )
        )
        .where(User.email == email.strip().lower())
    )
    if user is None or not verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        return None
    return user


def _decode_token(token: str, settings: Settings) -> int:
    try:
        payload = jwt.decode(
            token,
            _secret(settings),
            algorithms=["HS256"],
            issuer=settings.auth_issuer,
            audience=settings.auth_audience,
            options={"require": ["sub", "iss", "aud", "iat", "exp"]},
        )
    except (ExpiredSignatureError, InvalidTokenError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = _decode_token(credentials.credentials, settings)
    user = session.scalar(
        select(User)
        .options(
            selectinload(User.memberships).selectinload(
                OrganizationMembership.organization
            )
        )
        .where(User.id == user_id)
    )
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not any(
        membership.is_active and membership.organization.is_active
        for membership in user.memberships
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no active organization membership",
        )
    return user


def select_organization_membership(
    user: User,
    organization_id: int | None,
) -> OrganizationMembership:
    memberships = [
        membership
        for membership in user.memberships
        if membership.is_active and membership.organization.is_active
    ]
    if organization_id is None:
        if len(memberships) != 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An organization must be selected",
            )
        return memberships[0]
    membership = next(
        (
            item for item in memberships
            if item.organization_id == organization_id
        ),
        None,
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not an active member of this organization",
        )
    return membership


def get_organization_context(
    user: User = Depends(get_current_user),
    organization_header: str | None = Header(
        default=None,
        alias="X-Organization-ID",
    ),
) -> OrganizationContext:
    organization_id: int | None = None
    if organization_header is not None:
        try:
            organization_id = int(organization_header)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="X-Organization-ID must be an integer",
            ) from None
    membership = select_organization_membership(user, organization_id)
    return OrganizationContext(user, membership.organization_id, membership.role)


def require_roles(*roles: UserRole):
    def dependency(
        context: OrganizationContext = Depends(get_organization_context),
    ) -> OrganizationContext:
        if context.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role for this operation",
            )
        return context

    return dependency
