"""Accounts, sessions and role-based access."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from watchdog_backend.identity import rbac
from watchdog_backend.identity.passwords import hash_password, verify_password

from .conftest import TEST_PASSWORD


@pytest.fixture
def app_client(accounts):
    from watchdog_backend.main import app

    return TestClient(app)


def test_password_hashing() -> None:
    stored = hash_password("correct horse battery")
    assert stored.startswith("scrypt$") and "correct" not in stored
    assert verify_password("correct horse battery", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("anything", None)


def test_every_api_route_needs_sign_in_except_health(app_client) -> None:
    assert app_client.get("/api/health").status_code == 200
    for path in ("/api/domain", "/api/domains", "/api/watch", "/api/actions", "/api/auth/me"):
        assert app_client.get(path).status_code == 401, path


def test_login_sets_an_httponly_cookie_and_logout_ends_the_session(app_client) -> None:
    r = app_client.post(
        "/api/auth/login", json={"email": "a.rao@demo.watchdog", "password": TEST_PASSWORD}
    )
    assert r.status_code == 200
    assert "httponly" in r.headers["set-cookie"].lower()
    me = app_client.get("/api/auth/me", headers={"X-Domain": "insurance_claims"}).json()
    assert me["user"]["user_id"] == "a.rao" and me["business_role"] == "Head of Claims"
    assert "investigate" in me["permissions"] and "manage_users" not in me["permissions"]
    app_client.post("/api/auth/logout")
    assert app_client.get("/api/auth/me").status_code == 401


def test_wrong_password_gets_the_same_answer_as_unknown_email(app_client) -> None:
    a = app_client.post("/api/auth/login", json={"email": "a.rao@demo.watchdog", "password": "x"})
    b = app_client.post("/api/auth/login", json={"email": "nobody@x.y", "password": "x"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_business_roles_are_per_pack(client_as) -> None:
    c = client_as("a.rao")  # Head of Claims in insurance only
    assert (
        c.get("/api/auth/me", headers={"X-Domain": "insurance_claims"}).json()["business_role"]
        == "Head of Claims"
    )
    assert (
        c.get("/api/auth/me", headers={"X-Domain": "procure_to_pay"}).json()["business_role"]
        is None
    )


@pytest.mark.parametrize(
    ("user", "method", "path", "allowed"),
    [
        ("guest", "post", "/api/watch/run", False),
        ("m.khan", "post", "/api/watch/run", True),
        ("guest", "get", "/api/observability/summary", False),
        ("m.khan", "get", "/api/observability/summary", True),
        ("m.khan", "post", "/api/watch/simulate-month", False),
        ("m.khan", "get", "/api/auth/users", False),
        ("admin", "get", "/api/auth/users", True),
    ],
)
def test_role_matrix(client_as, user, method, path, allowed) -> None:
    status = getattr(client_as(user), method)(path).status_code
    assert (status != 403) is allowed, status


def test_rbac_matrix_is_monotonic() -> None:
    """Every permission a viewer has, an analyst has; every one an analyst has, an admin has."""
    for perm in rbac.PERMISSIONS:
        if rbac.allowed("viewer", perm):
            assert rbac.allowed("analyst", perm)
        if rbac.allowed("analyst", perm):
            assert rbac.allowed("admin", perm)


def test_admin_manages_users_and_deactivation_ends_sessions(client_as) -> None:
    admin = client_as("admin")
    r = admin.post(
        "/api/auth/users",
        json={
            "user_id": "t.test",
            "email": "t.test@example.com",
            "name": "T Test",
            "platform_role": "viewer",
            "password": "long-enough-pw",
            "pack_roles": {"procure_to_pay": "AP Manager"},
        },
    )
    assert r.status_code in (201, 409), r.text  # 409: left over from an earlier run
    assert (
        admin.post(
            "/api/auth/users",
            json={
                "user_id": "t.test",
                "email": "t.test@example.com",
                "name": "T",
                "platform_role": "viewer",
                "password": "long-enough-pw",
            },
        ).status_code
        == 409
    )
    admin.patch("/api/auth/users/t.test", json={"active": True, "platform_role": "analyst"})
    t = client_as("t.test")
    assert t.get("/api/auth/me").json()["user"]["platform_role"] == "analyst"
    assert admin.patch("/api/auth/users/t.test", json={"active": False}).status_code == 200
    assert t.get("/api/auth/me").status_code == 401  # sessions ended
    admin.patch("/api/auth/users/t.test", json={"active": True})


def test_short_passwords_are_rejected(client_as) -> None:
    r = client_as("admin").post(
        "/api/auth/users",
        json={
            "user_id": "short.pw",
            "email": "s@example.com",
            "name": "S",
            "platform_role": "viewer",
            "password": "short",
        },
    )
    assert r.status_code == 422


def test_cannot_remove_the_last_admin(client_as, accounts) -> None:
    with accounts.connect() as c:
        admins = c.execute(
            text("SELECT count(*) FROM identity.users WHERE platform_role = 'admin' AND active")
        ).scalar_one()
    if admins == 1:
        r = client_as("admin").patch("/api/auth/users/admin", json={"platform_role": "viewer"})
        assert r.status_code == 409


def test_act_as_is_audited_and_keeps_separation_of_duties(client_as) -> None:
    admin = client_as("admin")
    h = {"X-Domain": "insurance_claims"}
    me = admin.post("/api/auth/act-as", json={"user_id": "p.nair"}, headers=h).json()
    assert me["user"]["user_id"] == "p.nair" and me["real_user"]["user_id"] == "admin"
    assert me["business_role"] == "Quality Assurance Lead"
    # Acting as an analyst, the admin cannot manage users …
    assert "manage_users" not in me["permissions"]
    # … but can still list users to switch back (the real user is an admin).
    assert admin.get("/api/auth/users").status_code == 200
    events = [e["event"] for e in admin.get("/api/audit").json()]
    assert "identity.act_as" in events
    back = admin.post("/api/auth/act-as", json={"user_id": None}).json()
    assert back["user"]["user_id"] == "admin" and back["real_user"] is None


def test_non_admins_cannot_act_as(client_as) -> None:
    assert (
        client_as("m.khan").post("/api/auth/act-as", json={"user_id": "a.rao"}).status_code == 403
    )
