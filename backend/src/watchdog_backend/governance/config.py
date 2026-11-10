"""Governance configuration from the domain pack: demo users, roles, approval rules."""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from watchdog_backend.config import get_settings
from watchdog_backend.domain.pack import get_pack


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
def get_governance() -> Governance:
    path = Path(get_settings().domain_packs_dir) / get_pack().domain / "governance.yaml"
    return Governance.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
