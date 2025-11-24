"""Shared role definitions and helpers for Upstream."""

from __future__ import annotations

from enum import Enum
from typing import Iterable


class UserRole(str, Enum):
    """Supported application roles."""

    NONE = "NONE"
    READ = "READ"
    USER = "USER"
    APPROVEDADMIN = "APPROVEDADMIN"
    ADMIN = "ADMIN"


ROLE_RANK = {
    UserRole.NONE.value: -1,
    UserRole.READ.value: 0,
    UserRole.USER.value: 1,
    UserRole.APPROVEDADMIN.value: 2,
    UserRole.ADMIN.value: 2,
}

_VALID_ROLE_VALUES = set(ROLE_RANK.keys())


def normalize_role(value: str | None, *, default: UserRole = UserRole.NONE) -> str:
    """Normalize arbitrary text into a supported role value."""

    if not value:
        return default.value
    cleaned = value.strip().upper()
    if cleaned == "VIEWER":
        cleaned = UserRole.READ.value
    return cleaned if cleaned in _VALID_ROLE_VALUES else default.value


def is_valid_role(value: str | None) -> bool:
    return normalize_role(value) in _VALID_ROLE_VALUES


def normalize_roles(values: Iterable[str]) -> list[str]:
    return [normalize_role(value) for value in values]
