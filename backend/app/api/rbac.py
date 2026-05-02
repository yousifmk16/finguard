"""SEC-02: Role-based access control dependencies.

Composable FastAPI dependencies layered on SEC-01's
``get_current_user``. Endpoints opt in by declaring either::

    @router.get("/admin/...", dependencies=[Depends(require_admin)])
    def handler(): ...

or by binding the resolved user::

    def handler(user: CurrentUser = Depends(require_admin)):
        ...

Failure modes:
    * Missing / malformed / expired bearer token → 401 (raised inside
      ``get_current_user``; this module never overrides it).
    * Authenticated but wrong role → 403, ``forbidden: requires role X``.

SEC-03 wires these onto the anomaly, alert, KPI, and ingestion routers.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status

from app.api.auth import get_current_user
from app.schemas.auth import CurrentUser, Role


def require_any_role(*roles: Role) -> Callable[[CurrentUser], CurrentUser]:
    """Build a dependency that admits users whose role is one of ``roles``.

    Returns the resolved ``CurrentUser`` on success so handlers can bind
    the identity directly without re-running ``get_current_user``.
    """
    if not roles:
        raise ValueError("require_any_role needs at least one role")
    allowed = frozenset(roles)
    detail = f"forbidden: requires role {' or '.join(sorted(allowed))}"

    def _checker(
        user: CurrentUser = Depends(get_current_user),  # noqa: B008
    ) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=detail,
            )
        return user

    return _checker


def require_role(role: Role) -> Callable[[CurrentUser], CurrentUser]:
    """Convenience wrapper around ``require_any_role`` for a single role."""
    return require_any_role(role)


require_admin = require_any_role("admin")
require_analyst_or_admin = require_any_role("admin", "analyst")
