"""FastAPI dependencies: the signed-in principal, and permission checks."""

from collections.abc import Callable

from fastapi import HTTPException

from watchdog_backend.identity.service import Principal, current_principal


def principal() -> Principal:
    p = current_principal()
    if p is None:  # the middleware guarantees one on protected routes
        raise HTTPException(status_code=401, detail="Sign in required")
    return p


def require(permission: str) -> Callable[[], Principal]:
    def check() -> Principal:
        p = principal()
        if not p.can(permission):
            raise HTTPException(
                status_code=403,
                detail=f"Your role ({p.user.platform_role}) does not allow: "
                f"{permission.replace('_', ' ')}",
            )
        return p

    return check
