from __future__ import annotations

from app.pytas.http import TASClient


def user_has_allocation(username: str, charge_code: str) -> bool:
    """Check whether username has a TAS project with the given charge code."""
    if not username or not charge_code:
        return False
    target = charge_code.strip().lower()
    client = TASClient()
    projects = client.projects_for_user(username)
    return any((project.chargeCode or "").strip().lower() == target for project in projects)


__all__ = ["user_has_allocation"]
