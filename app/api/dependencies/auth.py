import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.api.v1.schemas.user import User
from app.pytas.http import TASClient # type: ignore[attr-defined]
from app.core.config import get_settings, Settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/token")
settings : Settings = get_settings()



def authenticate_user(username: str, password: str) -> dict[str, str | bool]:
    if settings.ENV == "dev":
        return {"status": "success", "message": "ok", "result": True}
    else:
        client = TASClient(
            baseURL=settings.TAS_URL,
            credentials={
                "username": settings.TAS_USER,
                "password": settings.TAS_SECRET,
            },
        )
        return client.authenticate(username, password) # type: ignore[no-any-return]


# Async function to get the current user based on the provided OAuth2 token
async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    if settings.ENV == "dev":
        return User(
            username="test",
        )

    try:
        user_dict = unhash(token)
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username = user_dict.get("username") or user_dict.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return User(
        username=username,
    )


# Function to decode a JWT token using the specified secret and algorithm
def unhash(token: str) -> dict[str, str]:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.ALG]) # type: ignore[no-any-return]

def hash(payload: dict[str, str]) -> str:
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.ALG)
