from datetime import datetime, timedelta, timezone

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.models import Organization, OrganizationMembership, User, UserRole
from app.services.auth import (
    authenticate_user,
    get_organization_context,
    hash_password,
    select_organization_membership,
    verify_password,
)
from fastapi import HTTPException


def bootstrap_payload(token: str = "test-bootstrap-token") -> dict:
    return {
        "bootstrap_token": token,
        "organization_name": "Acme Operations",
        "email": "admin@example.com",
        "password": "strong-password-123",
    }


def test_bootstrap_login_and_protected_endpoint(auth_client):
    response = auth_client.post("/api/auth/bootstrap-admin", json=bootstrap_payload())
    assert response.status_code == 201
    assert "password_hash" not in response.json()

    login = auth_client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "strong-password-123"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = auth_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "admin@example.com"

    protected = auth_client.get(
        "/api/employees", headers={"Authorization": f"Bearer {token}"}
    )
    assert protected.status_code == 200


def test_login_does_not_disclose_unknown_accounts_or_password_errors(auth_client):
    auth_client.post("/api/auth/bootstrap-admin", json=bootstrap_payload())
    unknown = auth_client.post(
        "/api/auth/login",
        json={"email": "unknown@example.com", "password": "wrong-password"},
    )
    incorrect = auth_client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "wrong-password"},
    )
    assert unknown.status_code == incorrect.status_code == 401
    assert unknown.json()["detail"] == incorrect.json()["detail"]


def test_missing_invalid_and_expired_tokens_are_rejected(auth_client):
    assert auth_client.get("/api/employees").status_code == 401
    assert auth_client.get(
        "/api/employees", headers={"Authorization": "Bearer invalid"}
    ).status_code == 401

    auth_client.post("/api/auth/bootstrap-admin", json=bootstrap_payload())
    expired = jwt.encode(
        {
            "sub": "1",
            "iss": "smartroster-ai",
            "aud": "smartroster-api",
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        },
        "test-auth-secret-that-is-at-least-32-characters",
        algorithm="HS256",
    )
    assert auth_client.get(
        "/api/employees", headers={"Authorization": f"Bearer {expired}"}
    ).status_code == 401


def test_password_hashing_and_role_validation(db_session):
    password = "strong-password-123"
    stored = hash_password(password)
    assert stored != password
    assert verify_password(password, stored)
    assert not verify_password("wrong-password", stored)

    user = User(
        email="manager@example.com",
        password_hash=stored,
        is_active=True,
    )
    organization = Organization(name="Manager Org", is_active=True)
    db_session.add_all([user, organization])
    db_session.flush()
    membership = OrganizationMembership(
        user_id=user.id,
        organization_id=organization.id,
        role=UserRole.MANAGER,
        is_active=True,
    )
    db_session.add(membership)
    db_session.commit()
    assert membership.role == UserRole.MANAGER


def test_organization_context_selects_single_active_membership(db_session):
    user = User(
        email="single@example.com",
        password_hash=hash_password("strong-password-123"),
        is_active=True,
    )
    organization = Organization(name="Single Org", is_active=True)
    db_session.add_all([user, organization])
    db_session.flush()
    membership = OrganizationMembership(
        user_id=user.id,
        organization_id=organization.id,
        role=UserRole.MANAGER,
        is_active=True,
    )
    user.memberships.append(membership)
    db_session.commit()

    selected = select_organization_membership(user, None)
    assert selected.organization_id == organization.id
    assert selected.role == UserRole.MANAGER
    context = get_organization_context(user, str(organization.id))
    assert context.organization_id == organization.id
    assert context.role == UserRole.MANAGER


def test_organization_context_requires_selection_for_multiple_memberships(db_session):
    user = User(
        email="multi@example.com",
        password_hash=hash_password("strong-password-123"),
        is_active=True,
    )
    first = Organization(name="First Org", is_active=True)
    second = Organization(name="Second Org", is_active=True)
    db_session.add_all([user, first, second])
    db_session.flush()
    user.memberships.extend([
        OrganizationMembership(
            organization_id=first.id, role=UserRole.ADMIN, is_active=True
        ),
        OrganizationMembership(
            organization_id=second.id, role=UserRole.EMPLOYEE, is_active=True
        ),
    ])
    db_session.commit()

    with pytest.raises(HTTPException) as error:
        select_organization_membership(user, None)
    assert error.value.status_code == 400
    assert select_organization_membership(user, second.id).role == UserRole.EMPLOYEE


def test_organization_context_rejects_inactive_membership_and_organization(db_session):
    user = User(
        email="inactive-membership@example.com",
        password_hash=hash_password("strong-password-123"),
        is_active=True,
    )
    inactive_membership_org = Organization(name="Inactive Membership Org", is_active=True)
    inactive_org = Organization(name="Inactive Org", is_active=False)
    db_session.add_all([user, inactive_membership_org, inactive_org])
    db_session.flush()
    user.memberships.extend([
        OrganizationMembership(
            organization_id=inactive_membership_org.id, role=UserRole.ADMIN, is_active=False
        ),
        OrganizationMembership(
            organization_id=inactive_org.id, role=UserRole.ADMIN, is_active=True
        ),
    ])
    db_session.commit()

    with pytest.raises(HTTPException) as error:
        select_organization_membership(user, inactive_membership_org.id)
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        select_organization_membership(user, inactive_org.id)
    assert error.value.status_code == 403


def test_organization_specific_role_check_does_not_cross_memberships(db_session):
    user = User(
        email="roles@example.com",
        password_hash=hash_password("strong-password-123"),
        is_active=True,
    )
    manager_org = Organization(name="Manager Role Org", is_active=True)
    employee_org = Organization(name="Employee Role Org", is_active=True)
    db_session.add_all([user, manager_org, employee_org])
    db_session.flush()
    user.memberships.extend([
        OrganizationMembership(
            organization_id=manager_org.id, role=UserRole.MANAGER, is_active=True
        ),
        OrganizationMembership(
            organization_id=employee_org.id, role=UserRole.EMPLOYEE, is_active=True
        ),
    ])
    db_session.commit()

    assert select_organization_membership(user, manager_org.id).role == UserRole.MANAGER
    assert select_organization_membership(user, employee_org.id).role == UserRole.EMPLOYEE


def test_inactive_accounts_cannot_authenticate(db_session):
    db_session.add(User(
        email="inactive@example.com",
        password_hash=hash_password("strong-password-123"),
        is_active=False,
    ))
    db_session.commit()
    assert authenticate_user(
        db_session, "inactive@example.com", "strong-password-123"
    ) is None


def test_production_requires_a_strong_signing_secret():
    with pytest.raises(ValidationError):
        Settings(environment="production")


def test_bootstrap_is_one_time_and_requires_token(auth_client):
    denied = auth_client.post(
        "/api/auth/bootstrap-admin",
        json=bootstrap_payload("wrong-token"),
    )
    assert denied.status_code == 403
    created = auth_client.post("/api/auth/bootstrap-admin", json=bootstrap_payload())
    assert created.status_code == 201
    repeated = auth_client.post("/api/auth/bootstrap-admin", json=bootstrap_payload())
    assert repeated.status_code == 409
