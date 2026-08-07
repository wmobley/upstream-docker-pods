from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import elevate_role_for_tas_allocation, get_admin_user, get_current_user
from app.api.v1.schemas.user import User
from app.api.v1.schemas.user_role import UserRoleResponse, UserRoleUpdate
from app.core.roles import normalize_role
from app.db.repositories.user_role_repository import UserRoleRepository
from app.db.session import get_db


router = APIRouter(prefix="/user-roles", tags=["user-roles"])

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

# Instance discovery (InstanceContext.tsx) calls this endpoint once per candidate
# project pod to decide whether it's even shown as an option, so it's the only
# place a Tapis-SSO user's TAS allocation gets checked (get_current_user() itself
# gates nearly every request and must not carry a live TAS call). This cache just
# throttles repeat TAS lookups for a user who hasn't (yet) got the allocation,
# so a user re-hitting this endpoint can't hammer the TAS service.
_TAS_CHECK_TTL_SECONDS = 300.0
_last_tas_check: dict[str, float] = {}


@router.get("/me", response_model=User)
def get_my_role(current_user: User = Depends(get_current_user)) -> User:
    """Self-lookup of the caller's own role in this project's DB. No admin gate."""
    now = time.monotonic()
    last_checked = _last_tas_check.get(current_user.username)
    if last_checked is not None and (now - last_checked) < _TAS_CHECK_TTL_SECONDS:
        logger.info(
            "user_roles_me extra=%s",
            {
                "username": current_user.username,
                "authenticated": True,
                "role": current_user.role,
                "tas_check": "throttled",
            },
        )
        return current_user

    _last_tas_check[current_user.username] = now
    initial_role = normalize_role(current_user.role)
    elevated_role = elevate_role_for_tas_allocation(current_user.username, initial_role)
    logger.info(
        "user_roles_me extra=%s",
        {
            "username": current_user.username,
            "authenticated": True,
            "initial_role": initial_role,
            "final_role": elevated_role,
            "tas_check": "ran",
        },
    )
    if elevated_role == current_user.role:
        return current_user
    return current_user.model_copy(update={"role": elevated_role})


@router.get("", response_model=list[UserRoleResponse])
def list_user_roles(
    _admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[UserRoleResponse]:
    repo = UserRoleRepository(db)
    records = repo.list_roles()
    return [UserRoleResponse.model_validate(record) for record in records]


@router.put("/{username}", response_model=UserRoleResponse)
def upsert_user_role(
    username: str,
    payload: UserRoleUpdate,
    _admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> UserRoleResponse:
    repo = UserRoleRepository(db)
    try:
        record = repo.upsert_role(username, payload.role.value)
    except ValueError as exc:  # pragma: no cover - validation guard
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return UserRoleResponse.model_validate(record)


@router.delete("/{username}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user_role(
    username: str,
    _admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> Response:
    repo = UserRoleRepository(db)
    deleted = repo.delete_role(username)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User role not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
