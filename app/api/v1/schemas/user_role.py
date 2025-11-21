from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.roles import UserRole


class UserRoleBase(BaseModel):
    username: str = Field(..., min_length=1)
    role: UserRole


class UserRoleResponse(UserRoleBase):
    class Config:
        from_attributes = True


class UserRoleUpdate(BaseModel):
    role: UserRole
