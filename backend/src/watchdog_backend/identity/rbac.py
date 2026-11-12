"""Role-based access control: what each platform role may do.

Two layers. The platform role (viewer < analyst < admin) gates capabilities in the app. The
business role a user holds in a pack (governance.yaml approvals) still decides WHICH actions
they may approve there, and separation of duties still applies. An admin cannot approve an
action unless their (effective) business role is an approver for it.
"""

from typing import Literal

PlatformRole = Literal["viewer", "analyst", "admin"]
ROLES: tuple[PlatformRole, ...] = ("viewer", "analyst", "admin")

_ALL = {"viewer", "analyst", "admin"}
_WORK = {"analyst", "admin"}

PERMISSIONS: dict[str, set[str]] = {
    "view": _ALL,  # dashboards, process, watch, investigations, actions, model comparison
    "ask": _ALL,  # policy Q&A and search
    "investigate": _WORK,  # start an investigation (spends LLM tokens)
    "propose_action": _WORK,
    "decide_action": _WORK,  # plus: an approver business role in the pack
    "execute_action": _WORK,
    "acknowledge_alert": _WORK,
    "run_monitors": _WORK,
    "view_observability": _WORK,
    "manage_documents": {"admin"},
    "manage_showcase": {"admin"},  # pick the runs visitors can replay
    "simulate_month": {"admin"},  # demo device: rewrites the data everyone sees
    "manage_users": {"admin"},
    "act_as": {"admin"},  # demo: act as another user (audited)
}

DESCRIPTIONS = {
    "viewer": "Read everything, ask policy questions. Cannot start investigations or act.",
    "analyst": "Investigate, propose, approve (with the right business role) and execute "
    "actions, run monitors, see observability.",
    "admin": "Everything, plus manage users, documents and showcase runs, simulate a month, act "
    "as another user for demos. Not rate-limited.",
}


def allowed(role: str, permission: str) -> bool:
    return role in PERMISSIONS.get(permission, set())


def permissions_for(role: str) -> list[str]:
    return sorted(p for p, roles in PERMISSIONS.items() if role in roles)
