"""GitHub OAuth (web application flow): the authorize URL, and the code-for-identity exchange.

Only identity is asked for (`read:user user:email`): no repository access. The access token is
used for two API calls and then discarded; it is never stored.
"""

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx2

from watchdog_backend.config import get_settings

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
API = "https://api.github.com"
SCOPE = "read:user user:email"
CALLBACK_PATH = "/api/auth/github/callback"


class GitHubError(Exception):
    """GitHub refused the code or could not be reached."""


@dataclass(frozen=True)
class GitHubIdentity:
    id: int
    login: str
    verified_emails: list[str]


def configured() -> bool:
    s = get_settings()
    return bool(s.github_client_id and s.github_client_secret)


def authorize_url(state: str, redirect_uri: str) -> str:
    return f"{AUTHORIZE_URL}?" + urlencode(
        {
            "client_id": get_settings().github_client_id,
            "redirect_uri": redirect_uri,
            "scope": SCOPE,
            "state": state,
            "allow_signup": "false",  # no point creating a GitHub account to get in here
        }
    )


def identity(code: str, redirect_uri: str, client: httpx2.Client | None = None) -> GitHubIdentity:
    s = get_settings()
    http = client or httpx2.Client(timeout=10.0)
    try:
        r = http.post(
            TOKEN_URL,
            data={
                "client_id": s.github_client_id,
                "client_secret": s.github_client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        token = r.json().get("access_token") if r.status_code == 200 else None
        if not token:
            raise GitHubError("GitHub did not accept the sign-in code")
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        user = http.get(f"{API}/user", headers=headers)
        emails = http.get(f"{API}/user/emails", headers=headers)
        if user.status_code != 200:
            raise GitHubError("GitHub did not return the user")
        u = user.json()
        verified = (
            [e["email"] for e in emails.json() if e.get("verified")]
            if emails.status_code == 200
            else []
        )
        return GitHubIdentity(id=int(u["id"]), login=u["login"], verified_emails=verified)
    except httpx2.HTTPError as exc:
        raise GitHubError(f"Could not reach GitHub: {exc.__class__.__name__}") from exc
    finally:
        if client is None:
            http.close()
