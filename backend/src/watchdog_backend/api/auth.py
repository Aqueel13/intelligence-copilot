"""Sign-in, the current user, acting as another user (admins, demos), and user management."""

import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, model_validator

from watchdog_backend.config import get_settings
from watchdog_backend.db import get_engine
from watchdog_backend.domain.pack import available_domains, current_domain, get_pack
from watchdog_backend.governance import audit
from watchdog_backend.governance.config import get_governance
from watchdog_backend.identity import github, limits, rbac
from watchdog_backend.identity import service as ids
from watchdog_backend.identity.deps import principal, require
from watchdog_backend.identity.middleware import COOKIE
from watchdog_backend.identity.service import Principal, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger(__name__)
_HTTP = {"unauthorized": 401, "forbidden": 403, "not_found": 404, "conflict": 409, "invalid": 422}


def _fail(exc: ids.IdentityError) -> HTTPException:
    return HTTPException(status_code=_HTTP[exc.code], detail=str(exc))


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class Me(BaseModel):
    user: UserOut
    real_user: UserOut | None  # set while an admin acts as someone else
    business_role: str | None  # in the active pack
    permissions: list[str]


def _me(p: Principal) -> Me:
    return Me(
        user=p.user,
        real_user=p.real if p.impersonating else None,
        business_role=p.user.pack_roles.get(current_domain()),
        permissions=rbac.permissions_for(p.user.platform_role),
    )


@router.post("/login", response_model=Me)
def login(body: LoginIn, response: Response) -> Me:
    with get_engine().connect() as conn:
        try:
            token, user = ids.login(conn, body.email, body.password)
        except ids.IdentityError as exc:
            raise _fail(exc) from exc
    _set_session_cookie(response, token)
    return _me(Principal(user=user, real=user))


def _set_session_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        COOKIE,
        token,
        max_age=s.session_hours * 3600,
        httponly=True,  # not readable by scripts
        samesite="lax",  # not sent on cross-site POSTs; sent on the redirect back from GitHub
        secure=s.cookie_secure,
        path="/",
    )


# ---------------------------------------------------------------------- GitHub sign-in

STATE_COOKIE = "wd_oauth_state"
STATE_PATH = "/api/auth/github"
# Why a GitHub sign-in failed, as the ?signin_error= the browser is sent back with.
GITHUB_ERRORS = {"not_found": "no_account", "conflict": "conflict", "forbidden": "inactive"}


@router.get("/providers")
def providers() -> dict[str, bool]:
    """Which sign-in methods the login form offers."""
    return {"password": True, "github": github.configured()}


def _callback_url(request: Request) -> str:
    base = get_settings().public_url or str(request.base_url)
    return base.rstrip("/") + github.CALLBACK_PATH


@router.get("/github/login")
def github_login(request: Request) -> RedirectResponse:
    """Start GitHub sign-in: a random state in a short-lived cookie, then off to GitHub."""
    if not github.configured():
        raise HTTPException(status_code=404, detail="GitHub sign-in is not configured")
    state = secrets.token_urlsafe(24)
    response = RedirectResponse(github.authorize_url(state, _callback_url(request)), 302)
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
        path=STATE_PATH,
    )
    return response


@router.get("/github/callback")
def github_callback(
    request: Request, code: str | None = None, state: str | None = None, error: str | None = None
) -> RedirectResponse:
    """GitHub sends the browser back here. The state must match the cookie set when sign-in
    started (so nobody can sign a victim into their own account); then the code is exchanged
    for the GitHub identity, which must match an account an admin created (D56)."""
    if not github.configured():
        raise HTTPException(status_code=404, detail="GitHub sign-in is not configured")

    def back(problem: str | None = None) -> RedirectResponse:
        response = RedirectResponse("/" + (f"?signin_error={problem}" if problem else ""), 302)
        response.delete_cookie(STATE_COOKIE, path=STATE_PATH)
        return response

    if error:
        return back("denied")
    expected = request.cookies.get(STATE_COOKIE)
    if not (code and state and expected and secrets.compare_digest(state, expected)):
        return back("state")
    try:
        who = github.identity(code, _callback_url(request))
    except github.GitHubError as exc:
        log.warning("GitHub sign-in failed: %s", exc)
        return back("github")
    with get_engine().connect() as conn:
        try:
            user = ids.github_account(conn, who.id, who.login, who.verified_emails)
        except ids.IdentityError as exc:
            log.info("GitHub user %s refused: %s", who.login, exc)
            return back(GITHUB_ERRORS.get(exc.code, "no_account"))
        token, _ = ids.start_session(conn, user.user_id)
    response = back()
    _set_session_cookie(response, token)
    return response


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE)
    if token:
        with get_engine().connect() as conn:
            ids.logout(conn, token)
    response.delete_cookie(COOKIE, path="/")


@router.get("/me", response_model=Me)
def me(p: Annotated[Principal, Depends(principal)]) -> Me:
    return _me(p)


class ActAsIn(BaseModel):
    user_id: str | None  # None: back to yourself


@router.post("/act-as", response_model=Me)
def act_as(body: ActAsIn, request: Request, p: Annotated[Principal, Depends(principal)]) -> Me:
    """Admins only: act as another user (for demos and support). Recorded in the audit log;
    governance treats the effective user as the actor, so separation of duties still holds."""
    token = request.cookies.get(COOKIE, "")
    with get_engine().connect() as conn:
        try:
            ids.act_as(conn, token, p, body.user_id)
        except ids.IdentityError as exc:
            raise _fail(exc) from exc
        audit.append(
            conn,
            p.real.user_id,
            "user",
            "identity.act_as",
            None,
            {"acting_as": body.user_id, "via": "ui"},
        )
        conn.commit()
        updated = ids.resolve(conn, token)
    return _me(updated)  # type: ignore[arg-type]


# ----------------------------------------------------------------------- management


class RoleInfo(BaseModel):
    platform_roles: dict[str, str]  # role -> what it may do
    permissions: dict[str, list[str]]  # permission -> roles
    business_roles: dict[str, list[str]]  # pack -> roles that approve something there


@router.get("/roles", response_model=RoleInfo)
def roles() -> RoleInfo:
    business = {}
    for d in available_domains():
        names = {r for rule in get_governance(d).approvals.values() for r in rule.roles}
        names |= {u.role for u in get_governance(d).users}
        business[d] = sorted(names)
    return RoleInfo(
        # assignable roles only: "visitor" is built in for anyone not signed in
        platform_roles={r: rbac.DESCRIPTIONS[r] for r in rbac.ROLES},
        permissions={k: sorted(v) for k, v in rbac.PERMISSIONS.items()},
        business_roles=business,
    )


def real_admin(p: Annotated[Principal, Depends(principal)]) -> Principal:
    """The person really signed in is an admin (also while acting as someone else)."""
    if p.real.platform_role != "admin":
        raise HTTPException(status_code=403, detail="Admins only")
    return p


@router.get("/users", response_model=list[UserOut])
def users(_: Annotated[Principal, Depends(real_admin)]) -> list[UserOut]:
    """Admins: every account (for user management and the act-as picker)."""
    with get_engine().connect() as conn:
        return ids.list_users(conn)


class UserIn(BaseModel):
    user_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,40}$")
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+$", max_length=200)
    name: str = Field(min_length=1, max_length=100)
    platform_role: rbac.PlatformRole
    password: str | None = Field(None, min_length=10, max_length=200)
    github_login: str | None = Field(None, max_length=40)
    pack_roles: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def can_sign_in(self) -> "UserIn":
        if not self.password and not (self.github_login or "").strip():
            raise ValueError("Give an initial password, a GitHub user name, or both")
        return self


def _check_packs(pack_roles: dict[str, str] | None) -> None:
    for d in pack_roles or {}:
        if d not in available_domains():
            raise HTTPException(status_code=422, detail=f"Unknown pack '{d}'")


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserIn, p: Annotated[Principal, Depends(require("manage_users"))]) -> UserOut:
    _check_packs(body.pack_roles)
    with get_engine().connect() as conn:
        try:
            user = ids.create_user(
                conn,
                body.user_id,
                body.email,
                body.name,
                body.platform_role,
                body.password,
                body.pack_roles,
                body.github_login,
            )
        except ids.IdentityError as exc:
            raise _fail(exc) from exc
        audit.append(
            conn,
            p.real.user_id,
            "user",
            "identity.user_created",
            None,
            {
                "user": body.user_id,
                "platform_role": body.platform_role,
                "pack_roles": body.pack_roles,
                "github_login": body.github_login,
                "via": "ui",
            },
        )
        conn.commit()
        return user


class UserPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    platform_role: rbac.PlatformRole | None = None
    active: bool | None = None
    password: str | None = Field(None, min_length=10, max_length=200)
    github_login: str | None = Field(None, max_length=40)  # "" removes the link
    pack_roles: dict[str, str] | None = None


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: str, body: UserPatch, p: Annotated[Principal, Depends(require("manage_users"))]
) -> UserOut:
    _check_packs(body.pack_roles)
    with get_engine().connect() as conn:
        target = ids.get_user(conn, user_id)
        demoting_admin = (
            target is not None
            and target.platform_role == "admin"
            and (body.active is False or (body.platform_role and body.platform_role != "admin"))
        )
        if demoting_admin and ids.admin_count(conn) <= 1:
            raise HTTPException(status_code=409, detail="Keep at least one active admin")
        try:
            user = ids.update_user(conn, user_id, **body.model_dump(exclude_none=True))
        except ids.IdentityError as exc:
            raise _fail(exc) from exc
        changes = body.model_dump(exclude_none=True, exclude={"password"})
        if body.password:
            changes["password"] = "reset"
        audit.append(
            conn,
            p.real.user_id,
            "user",
            "identity.user_updated",
            None,
            {"user": user_id, "changes": changes, "via": "ui"},
        )
        conn.commit()
        return user


@router.get("/packs")
def packs() -> list[dict[str, str]]:
    return [{"domain": d, "display_name": get_pack(d).display_name} for d in available_domains()]


class UsageWindow(BaseModel):
    scope: str  # user (rolling hour) | everyone (rolling day)
    limit: int  # 0 = no limit
    used: int
    resets_in: int


class Usage(BaseModel):
    exempt: bool
    limits: dict[str, list[UsageWindow]]  # per action: investigate, ask


@router.get("/usage", response_model=Usage)
def usage(who: Annotated[Principal, Depends(principal)]) -> Usage:
    """How much of the rate limits the signed-in person has used (see identity/limits.py)."""
    with get_engine().connect() as conn:
        return Usage(
            exempt=limits.exempt(who),
            limits={
                a: [UsageWindow(**vars(w)) for w in limits.status(conn, who, a)]
                for a in limits.ACTIONS
            },
        )
