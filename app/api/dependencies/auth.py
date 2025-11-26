import logging
import jwt
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Header, Request, status
from fastapi.security import OAuth2PasswordBearer

from app.api.v1.schemas.user import User
from app.core.config import get_settings, Settings
from app.core.roles import ROLE_RANK, UserRole as UserRoleEnum, normalize_role as normalize_role_value
from app.db.repositories.user_role_repository import UserRoleRepository
from app.db.session import SessionLocal
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
    skip_enforcement = settings.ENV == "dev" and not settings.TAPIS_ENFORCE_AUTH_IN_DEV
    if skip_enforcement:
        logger.debug(
            "Credential enforcement disabled in dev mode for username=%s (enforce flag disabled)",
            username,
        )

    # Require username/password unless enforcement is explicitly disabled.
    if not username or not password:
        if skip_enforcement:
            return AuthResult(success=True)
        logger.info("Login rejected: missing username/password")
        return AuthResult(success=False, error="Missing username or password")

    if tapis_auth_client is not None:
        try:
            outcome = tapis_auth_client.authenticate(username, password)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unexpected error while calling TapisAuthClient: %s", exc)
            if skip_enforcement:
                # Fall back to local auth without tapis tokens
                return AuthResult(success=True, tapis_tokens=None)
            return AuthResult(success=False, error="Tapis authentication failed. See logs for details.")

        if outcome.tokens:
            logger.info("Tapis authentication succeeded for username=%s", username)
            return AuthResult(success=True, tapis_tokens=outcome.tokens)
        # Tapis did not return tokens (authentication failed or tokens missing).
        logger.info("Tapis authentication did not return tokens for %s: %s", username, outcome.error)
        if skip_enforcement:
            return AuthResult(success=True, tapis_tokens=None)
        failure_message = outcome.error or "Invalid username or password"
        return AuthResult(success=False, error=failure_message)

    # For local authentication (no Tapis client configured) we accept any non-empty username/password
    # combination as a successful login. This keeps non-Tapis deployments working.
    logger.info("Local auth successful for username=%s (no Tapis client configured)", username)
    return AuthResult(success=True, tapis_tokens=None)


def _default_role() -> str:
    env = (settings.ENV or "").lower()
    if env in {"dev", "test"} and not settings.TAPIS_ENFORCE_AUTH_IN_DEV:
        return UserRoleEnum.ADMIN.value
    return UserRoleEnum.NONE.value


def resolve_user_role(username: str, _tapis_access_token: str | None) -> str:
    normalized_username = (username or "").strip()
    if not normalized_username:
        return _default_role()

    try:
        with SessionLocal() as db:
            repo = UserRoleRepository(db)
            record = repo.get_by_username(normalized_username)
            if record:
                return normalize_role_value(record.role, default=UserRoleEnum.NONE)
    except Exception:  # pragma: no cover - defensive fallback
        logger.exception("Failed to resolve role for %s", username)

    default_admin_candidates = settings.DEFAULT_ADMIN_USERS or []
    default_admins = {user.strip().lower() for user in default_admin_candidates if user}
    if normalized_username.lower() in default_admins:
        return UserRoleEnum.ADMIN.value

    return _default_role()


def _role_allows(role: str | None, minimum: str) -> bool:
    current_rank = ROLE_RANK.get(normalize_role_value(role, default=UserRoleEnum.NONE), -1)
    required_rank = ROLE_RANK.get(normalize_role_value(minimum, default=UserRoleEnum.NONE), -1)
    return current_rank >= required_rank


# Async function to get the current user based on the provided OAuth2 token
async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    if settings.ENV == "dev":
        return User(
            username="test",
            role=_default_role(),
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
        role=normalize_role_value(user_dict.get("role"), default=UserRoleEnum.NONE),
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


async def get_viewer_user(current_user: User = Depends(get_current_user)) -> User:
    if not _role_allows(getattr(current_user, "role", None), "READ"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Viewer role required")
    return current_user


async def get_edit_user(current_user: User = Depends(get_current_user)) -> User:
    if not _role_allows(getattr(current_user, "role", None), "USER"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Edit role required")
    return current_user


async def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if not _role_allows(getattr(current_user, "role", None), "ADMIN"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return current_user
