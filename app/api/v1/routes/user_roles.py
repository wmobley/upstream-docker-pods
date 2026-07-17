from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_admin_user, get_current_user
from app.api.v1.schemas.user import User
from app.api.v1.schemas.user_role import UserRoleResponse, UserRoleUpdate
from app.db.repositories.user_role_repository import UserRoleRepository
from app.db.session import get_db


router = APIRouter(prefix="/user-roles", tags=["user-roles"])


@router.get("/me", response_model=User)
def get_my_role(current_user: User = Depends(get_current_user)) -> User:
    """Self-lookup of the caller's own role in this project's DB. No admin gate."""
    return current_user


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
