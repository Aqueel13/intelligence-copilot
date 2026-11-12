"""GitHub sign-in: only accounts an admin created (D56), matched safely, with a checked state."""

import uuid
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from watchdog_backend.identity import github
from watchdog_backend.identity import service as ids
from watchdog_backend.identity.github import GitHubError, GitHubIdentity
from watchdog_backend.identity.middleware import COOKIE


@pytest.fixture
def configured(monkeypatch):
    from watchdog_backend.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "github_client_id", "test-client")
    monkeypatch.setattr(s, "github_client_secret", "test-secret")
    monkeypatch.setattr(s, "public_url", "https://watchdog.example")


@pytest.fixture
def client(accounts):
    from watchdog_backend.main import app

    return TestClient(app, follow_redirects=False)


@pytest.fixture
def user(accounts):
    """A fresh analyst; returns a factory so a test can choose the GitHub link and email."""
    made = []

    def make(github_login=None, email=None, active=True):
        uid = f"gh-{uuid.uuid4().hex[:8]}"
        with accounts.connect() as conn:
            ids.create_user(
                conn, uid, email or f"{uid}@example.org", uid, "analyst", None, {}, github_login
            )
            if not active:
                ids.update_user(conn, uid, active=False)
        made.append(uid)
        return uid

    yield make
    with accounts.connect() as conn:
        conn.execute(text("DELETE FROM identity.users WHERE user_id = ANY(:u)"), {"u": made})
        conn.commit()


def sign_in(client, monkeypatch, who: GitHubIdentity | Exception):
    """Run the whole flow with GitHub's side replaced; returns the final redirect target."""

    def fake_identity(code, redirect_uri, client=None):
        assert code == "the-code"
        assert redirect_uri == "https://watchdog.example" + github.CALLBACK_PATH
        if isinstance(who, Exception):
            raise who
        return who

    monkeypatch.setattr(github, "identity", fake_identity)
    start = client.get("/api/auth/github/login")
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    done = client.get(f"/api/auth/github/callback?code=the-code&state={state}")
    assert done.status_code == 302
    return done.headers["location"]


def gh(id_: int, login: str, emails=()) -> GitHubIdentity:
    return GitHubIdentity(id=id_, login=login, verified_emails=list(emails))


def test_not_offered_until_configured(client) -> None:
    assert client.get("/api/auth/providers").json() == {"password": True, "github": False}
    assert client.get("/api/auth/github/login").status_code == 404
    assert client.get("/api/auth/github/callback?code=x&state=y").status_code == 404


def test_start_sends_the_browser_to_github_with_a_state_cookie(client, configured) -> None:
    assert client.get("/api/auth/providers").json()["github"] is True
    r = client.get("/api/auth/github/login")
    assert r.status_code == 302
    url = urlparse(r.headers["location"])
    q = parse_qs(url.query)
    assert url.netloc == "github.com" and q["client_id"] == ["test-client"]
    assert q["redirect_uri"] == ["https://watchdog.example/api/auth/github/callback"]
    assert q["scope"] == ["read:user user:email"] and q["allow_signup"] == ["false"]
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"wd_oauth_state={q['state'][0]}") and "HttpOnly" in cookie


def test_a_wrong_or_missing_state_is_refused(client, configured, monkeypatch, user) -> None:
    uid = user(github_login="octo-state")
    monkeypatch.setattr(github, "identity", lambda *a, **k: gh(1, "octo-state"))
    client.get("/api/auth/github/login")
    r = client.get("/api/auth/github/callback?code=the-code&state=forged")
    assert r.headers["location"] == "/?signin_error=state"
    assert COOKIE not in client.cookies
    fresh = TestClient(client.app, follow_redirects=False)  # no state cookie at all
    r = fresh.get("/api/auth/github/callback?code=the-code&state=anything")
    assert r.headers["location"] == "/?signin_error=state"
    assert fresh.get("/api/auth/me").json()["user"]["user_id"] != uid


def test_signs_in_the_linked_account_and_remembers_the_github_id(
    client, configured, monkeypatch, user, accounts
) -> None:
    uid = user(github_login="Octo-Cat")
    assert sign_in(client, monkeypatch, gh(4242, "octo-cat")) == "/"
    assert client.get("/api/auth/me").json()["user"]["user_id"] == uid
    with accounts.connect() as conn:
        assert (
            conn.execute(
                text("SELECT github_id FROM identity.users WHERE user_id = :u"), {"u": uid}
            ).scalar_one()
            == 4242
        )

    # Renamed on GitHub: the recorded id still matches.
    other = TestClient(client.app, follow_redirects=False)
    assert sign_in(other, monkeypatch, gh(4242, "octo-renamed")) == "/"
    assert other.get("/api/auth/me").json()["user"]["user_id"] == uid

    # Someone else later takes the old user name: refused, not signed in as this account.
    thief = TestClient(client.app, follow_redirects=False)
    assert sign_in(thief, monkeypatch, gh(9999, "Octo-Cat")) == "/?signin_error=conflict"
    assert COOKIE not in thief.cookies


def test_a_verified_email_matches_an_account_without_a_github_name(
    client, configured, monkeypatch, user
) -> None:
    uid = user(email="Person@Example.org")
    who = gh(5151, "someone", emails=["other@x.io", "person@example.org"])
    assert sign_in(client, monkeypatch, who) == "/"
    assert client.get("/api/auth/me").json()["user"]["user_id"] == uid


def test_no_account_no_entry(client, configured, monkeypatch, user, accounts) -> None:
    with accounts.connect() as conn:
        before = conn.execute(text("SELECT count(*) FROM identity.users")).scalar_one()
    who = gh(777, "stranger", emails=["stranger@example.org"])
    assert sign_in(client, monkeypatch, who) == "/?signin_error=no_account"
    assert COOKIE not in client.cookies
    assert client.get("/api/auth/me").json()["user"]["platform_role"] == "visitor"
    with accounts.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM identity.users")).scalar_one() == before


def test_deactivated_accounts_and_github_failures(client, configured, monkeypatch, user) -> None:
    user(github_login="octo-gone", active=False)
    assert sign_in(client, monkeypatch, gh(31, "octo-gone")) == "/?signin_error=inactive"
    assert sign_in(client, monkeypatch, GitHubError("down")) == "/?signin_error=github"
    r = client.get("/api/auth/github/callback?error=access_denied&state=x")
    assert r.headers["location"] == "/?signin_error=denied"


def test_admin_links_github_names(client_as, accounts) -> None:
    admin = client_as("admin")
    base = {"name": "N", "platform_role": "viewer", "pack_roles": {}}
    uid = f"gh-{uuid.uuid4().hex[:8]}"
    r = admin.post(
        "/api/auth/users",
        json={**base, "user_id": uid, "email": f"{uid}@x.org", "github_login": "@New-Person"},
    )
    assert r.status_code == 201 and r.json()["github_login"] == "New-Person"
    no_way_in = {**base, "user_id": uid + "b", "email": f"{uid}b@x.org"}
    assert admin.post("/api/auth/users", json=no_way_in).status_code == 422
    dup = {**no_way_in, "github_login": "new-person"}
    assert admin.post("/api/auth/users", json=dup).status_code == 409
    bad = {**no_way_in, "github_login": "not a name"}
    assert admin.post("/api/auth/users", json=bad).status_code == 422
    r = admin.patch(f"/api/auth/users/{uid}", json={"github_login": ""})
    assert r.status_code == 200 and r.json()["github_login"] is None
    with accounts.connect() as conn:
        conn.execute(text("DELETE FROM identity.users WHERE user_id = :u"), {"u": uid})
        conn.commit()


def test_identity_exchange_keeps_only_verified_emails() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/login/oauth/access_token":
            if b"code=good" not in request.content:
                return httpx2.Response(200, json={"error": "bad_verification_code"})
            return httpx2.Response(200, json={"access_token": "tok"})
        assert request.headers["authorization"] == "Bearer tok"
        if request.url.path == "/user":
            return httpx2.Response(200, json={"id": 12, "login": "octo"})
        return httpx2.Response(
            200,
            json=[
                {"email": "a@x.io", "verified": True},
                {"email": "b@x.io", "verified": False},
            ],
        )

    http = httpx2.Client(transport=httpx2.MockTransport(handler))
    who = github.identity("good", "https://w/cb", client=http)
    assert who == GitHubIdentity(id=12, login="octo", verified_emails=["a@x.io"])
    with pytest.raises(GitHubError):
        github.identity("bad", "https://w/cb", client=http)
