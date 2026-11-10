"""Governance configuration from the domain pack: demo users, roles, approval rules."""

from functools import lru_cache

import yaml
from pydantic import BaseModel, ConfigDict

from watchdog_backend.domain.pack import current_domain, pack_file


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class User(_Strict):
    id: str
    name: str
    role: str


class ApprovalRule(_Strict):
    roles: list[str]
    basis: str


class Rules(_Strict):
    separation_of_duties: bool = True


class Governance(_Strict):
    users: list[User]
    approvals: dict[str, ApprovalRule]
    rules: Rules

    def user(self, user_id: str) -> User | None:
        return next((u for u in self.users if u.id == user_id), None)


@lru_cache
def _governance(domain: str) -> Governance:
    path = pack_file("governance.yaml", domain=domain)
    return Governance.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def get_governance(domain: str | None = None) -> Governance:
    """A pack's governance (the active pack by default; cached per pack)."""
    return _governance(domain or current_domain())
