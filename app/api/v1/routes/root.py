# mypy: allow-untyped-calls

import jwt
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from app.api.dependencies.auth import AuthResult, authenticate_user, resolve_user_role, ensure_ckan_membership
from app.core.config import get_settings
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    tapis_access_token: str | None = None
    tapis_refresh_token: str | None = None
    tapis_expires_at: int | None = None
    username: str | None = None
    role: str | None = None

def get_jwt_secret() -> str:
    settings = get_settings()
    return settings.JWT_SECRET

def create_token(username: str, jwt_secret: str, role: str | None = None) -> str:
    payload: dict[str, str] = {"username": username}
    if role:
        payload["role"] = role
    return jwt.encode(payload, jwt_secret, algorithm="HS256")

# Route for user authentication and token generation
@router.post("/token", tags=["auth"])
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    jwt_secret: str = Depends(get_jwt_secret)
) -> LoginResponse:
    auth_result: AuthResult = authenticate_user(form_data.username, form_data.password)
    if not auth_result.success:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=auth_result.error or "Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Create jwt token
    tapis_tokens = auth_result.tapis_tokens or {}
    role = resolve_user_role(form_data.username, tapis_tokens.get("access_token"))
    try:
        ensure_ckan_membership(form_data.username, role)
    except Exception:  # pragma: no cover - defensive log
        logger.exception("Unable to ensure CKAN membership for %s", form_data.username)
    return LoginResponse(
        access_token=create_token(form_data.username, jwt_secret, role),
        token_type="bearer",
        tapis_access_token=tapis_tokens.get("access_token"),
        tapis_refresh_token=tapis_tokens.get("refresh_token"),
        tapis_expires_at=tapis_tokens.get("expires_at"),
        username=form_data.username,
        role=role,
    )
