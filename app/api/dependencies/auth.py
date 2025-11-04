import logging
import jwt
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Header, Request, status
from fastapi.security import OAuth2PasswordBearer

from app.api.v1.schemas.user import User
from app.core.config import get_settings, Settings
from app.tapis import TapisAuthClient

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/token")
settings: Settings = get_settings()

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

tapis_auth_client: TapisAuthClient | None = None
if settings.TAPIS_BASE_URL and settings.TAPIS_TENANT_ID:
    tapis_auth_client = TapisAuthClient(
        base_url=settings.TAPIS_BASE_URL,
        tenant_id=settings.TAPIS_TENANT_ID,
    )


@dataclass(slots=True)
class AuthResult:
    success: bool
    tapis_tokens: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


def authenticate_user(username: str, password: str) -> AuthResult:
    # If running in dev and TAPIS enforcement is explicitly disabled, accept
    # missing/empty credentials and short-circuit as a successful local auth.
    if settings.ENV == "dev" and not settings.TAPIS_ENFORCE_AUTH_IN_DEV:
        logger.debug(
            "Skipping credential enforcement in dev mode for username=%s (enforce flag disabled)",
            username,
        )
        return AuthResult(success=True)

    # Require username/password in non-dev (or when enforcement is enabled)
    if not username or not password:
        logger.info("Login rejected: missing username/password")
        return AuthResult(success=False, error="Missing username or password")

    # For local authentication we accept any non-empty username/password
    # combination as a successful local login. If a TapisAuthClient is
    # configured, attempt to authenticate against Tapis and include any
    # returned tokens in the result so the login response can surface a
    # tapis_access_token for pod environments.
    logger.info("Local auth successful for username=%s", username)

    if tapis_auth_client is not None:
        try:
            outcome = tapis_auth_client.authenticate(username, password)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unexpected error while calling TapisAuthClient: %s", exc)
            # Fall back to local auth without tapis tokens
            return AuthResult(success=True, tapis_tokens=None)

        if outcome.tokens:
            logger.info("Tapis authentication succeeded for username=%s", username)
            return AuthResult(success=True, tapis_tokens=outcome.tokens)
        else:
            # Tapis did not return tokens (or authentication failed). Log and
            # fall back to local success so that local development and other
            # non-Tapis flows continue to work.
            logger.info("Tapis authentication did not return tokens for %s: %s", username, outcome.error)
            return AuthResult(success=True, tapis_tokens=None)

    return AuthResult(success=True, tapis_tokens=None)


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
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.ALG])  # type: ignore[no-any-return]


def hash(payload: dict[str, str]) -> str:
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.ALG)


def get_tapis_token_header(
    x_tapis_token: str | None = Header(default=None, alias="X-TAPIS-TOKEN"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> str:
    """
    Retrieve a Tapis access token for CKAN proxy calls.

    Preference order:
    1. Explicit ``X-TAPIS-TOKEN`` header.
    2. Bearer token from the Authorization header (if provided).
    """
    if x_tapis_token:
        return x_tapis_token

    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1]

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Tapis access token required for CKAN integration. Provide X-TAPIS-TOKEN or a Bearer token.",
    )


def get_tapis_token_header_optional(
    x_tapis_token: str | None = Header(default=None, alias="X-TAPIS-TOKEN"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> str | None:
    if x_tapis_token:
        return x_tapis_token
    return None

async def get_current_user_optional(request: Request) -> User | None:
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1]
        try:
            return await get_current_user(token=token)
        except HTTPException:
            return None
    return None


def get_oauth_token_optional(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1]
    return None
