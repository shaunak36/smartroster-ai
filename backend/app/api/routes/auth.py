from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import Organization, OrganizationMembership, User, UserRole
from app.schemas.auth import (
    BootstrapAdminRequest,
    LoginRequest,
    MembershipRead,
    TokenResponse,
    UserRead,
)
from app.services.auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
    hash_password,
)

router = APIRouter(prefix="/api/auth", tags=["authentication"])


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user = authenticate_user(db, payload.email, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        token = create_access_token(user, settings)
    except HTTPException:
        raise
    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_minutes * 60,
    )


@router.post("/bootstrap-admin", response_model=UserRead, status_code=201)
def bootstrap_admin(
    payload: BootstrapAdminRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not settings.bootstrap_admin_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Administrator provisioning is not configured",
        )
    if payload.bootstrap_token != settings.bootstrap_admin_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid administrator provisioning token",
        )
    if db.scalar(select(func.count(User.id))) != 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Administrator provisioning is already complete",
        )
    organization_name = payload.organization_name.strip()
    if not organization_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Organization name must not be blank",
        )
    organization = db.scalar(
        select(Organization).where(Organization.name == organization_name)
    )
    if organization is None:
        organization = Organization(name=organization_name, is_active=True)
    user = User(
        email=payload.email.strip().lower(),
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    try:
        if organization.id is None:
            db.add(organization)
        db.add(user)
        db.flush()
        db.add(OrganizationMembership(
            organization_id=organization.id,
            user_id=user.id,
            role=UserRole.ADMIN,
            is_active=True,
        ))
        db.commit()
        db.refresh(user)
        return user
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Administrator provisioning failed",
        ) from exc


@router.get("/me", response_model=UserRead)
def current_user(
    user: User = Depends(get_current_user),
):
    return user


@router.get("/memberships", response_model=list[MembershipRead])
def memberships(
    user: User = Depends(get_current_user),
):
    return user.memberships
