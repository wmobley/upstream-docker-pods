from __future__ import annotations

from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.roles import normalize_role, UserRole
from app.db.models.user_role import UserRole as UserRoleModel


class UserRoleRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _normalize_username(username: str) -> str:
        return username.strip().lower()

    def list_roles(self) -> list[UserRoleModel]:
        return self.db.query(UserRoleModel).order_by(UserRoleModel.username).all()

    def get_by_username(self, username: str) -> Optional[UserRoleModel]:
        normalized = self._normalize_username(username)
        if not normalized:
            return None
        return (
            self.db.query(UserRoleModel)
            .filter(func.lower(UserRoleModel.username) == normalized)
            .first()
        )

    def upsert_role(self, username: str, role: str) -> UserRoleModel:
        normalized_username = self._normalize_username(username)
        if not normalized_username:
            raise ValueError("Username is required")
        normalized_role = normalize_role(role, default=UserRole.READ)
        existing = self.get_by_username(normalized_username)
        if existing:
            existing.role = normalized_role
            record = existing
        else:
            record = UserRoleModel(username=normalized_username, role=normalized_role)
            self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def delete_role(self, username: str) -> bool:
        normalized = self._normalize_username(username)
        if not normalized:
            return False
        existing = self.get_by_username(normalized)
        if not existing:
            return False
        self.db.delete(existing)
        self.db.commit()
        return True
