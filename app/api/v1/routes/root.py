from typing import Dict
# mypy: allow-untyped-calls

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from app.api.dependencies.auth import authenticate_user
from app.core.config import get_settings
from pydantic import BaseModel

router = APIRouter()

class LoginResponse(BaseModel):
    access_token: str
    token_type: str

def get_jwt_secret() -> str:
    settings = get_settings()
    return settings.JWT_SECRET

def create_token(username: str, jwt_secret: str) -> str:
    return jwt.encode({"username": username}, jwt_secret, algorithm="HS256")

# Route for user authentication and token generation
@router.post("/token", tags=["auth"])
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    jwt_secret: str = Depends(get_jwt_secret)
) -> LoginResponse:
    authenticated = authenticate_user(form_data.username, form_data.password)
    if not authenticated:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    # Create jwt token
    return LoginResponse(
        access_token=create_token(form_data.username, jwt_secret),
        token_type="bearer",
    )
