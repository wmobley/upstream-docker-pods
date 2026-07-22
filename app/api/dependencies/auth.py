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
from app.tapis import TapisAuthClient, TapisTokenVerifier
from app.services.ckan_service import CKANError, get_ckan_service
from app.services.tas_service import user_has_allocation

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/token", auto_error=False)
settings: Settings = get_settings()

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

tapis_auth_client: TapisAuthClient | None = None
tapis_token_verifier: TapisTokenVerifier | None = None
if settings.TAPIS_BASE_URL and settings.TAPIS_TENANT_ID:
    tapis_auth_client = TapisAuthClient(
        base_url=settings.TAPIS_BASE_URL,
        tenant_id=settings.TAPIS_TENANT_ID,
    )
    tapis_token_verifier = TapisTokenVerifier(
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
                # Fall back to local auth without tapis tokens when explicitly allowed.
                return AuthResult(success=True, tapis_tokens=None)
            return AuthResult(success=False, error="Tapis authentication failed. See logs for details.")

        if outcome.tokens:
            logger.info("Tapis authentication succeeded for username=%s", username)
            return AuthResult(success=True, tapis_tokens=outcome.tokens)
        # Tapis did not return tokens (authentication failed or tokens missing).
        logger.info("Tapis authentication did not return tokens for %s: %s", username, outcome.error)
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

def ensure_ckan_membership(username: str, role: str) -> None:
    normalized_username = (username or "").strip()
    normalized_role = normalize_role_value(role, default=UserRoleEnum.NONE)

    eligible_roles = {
        UserRoleEnum.USER.value,
        UserRoleEnum.ADMIN.value,
        UserRoleEnum.APPROVEDADMIN.value,
    }
    if not normalized_username or normalized_role not in eligible_roles:
        return

    organization = (settings.CKAN_ORGANIZATION or "upstream").strip()
    admin_api_key = (settings.CKAN_ADMIN_API_KEY or "").strip()
    admin_username = (settings.CKAN_ADMIN_USERNAME or "dso_test").strip()
    if not organization or not admin_api_key:
        logger.info(
            "Skipping CKAN membership grant for %s: missing organization or admin API key",
            normalized_username,
        )
        return

    ckan_client = get_ckan_service()
    if not ckan_client:
        logger.info(
            "Skipping CKAN membership grant for %s: CKAN integration not configured",
            normalized_username,
        )
        return

    try:
        ckan_client.ensure_user_in_organization(
            api_key=admin_api_key,
            organization=organization,
            username=normalized_username,
            role="admin",
            requestor=admin_username or None,
        )
    except CKANError as exc:
        logger.warning(
            "CKAN membership grant failed for %s in %s: %s",
            normalized_username,
            organization,
            exc,
        )
    except Exception:  # pragma: no cover - defensive log
        logger.exception("Unexpected error while ensuring CKAN membership for %s", normalized_username)


def elevate_role_for_tas_allocation(username: str, current_role: str) -> str:
    """Elevate a user to USER role if they hold the configured TAS allocation.

    Only runs on the primary instance (IS_PRIMARY_INSTANCE=true) — bundle-created
    project pods never set this env var, so this is a no-op there. Never
    downgrades an existing USER/APPROVEDADMIN/ADMIN role, and fails safe
    (returns current_role unchanged) if the TAS check or DB write errors.
    """
    if not settings.IS_PRIMARY_INSTANCE:
        return current_role

    normalized_username = (username or "").strip()
    if not normalized_username:
        return current_role

    normalized_current = normalize_role_value(current_role, default=UserRoleEnum.NONE)
    if ROLE_RANK.get(normalized_current, -1) >= ROLE_RANK[UserRoleEnum.USER.value]:
        return current_role

    try:
        has_allocation = user_has_allocation(normalized_username, settings.PRIMARY_ALLOCATION_CHARGE_CODE)
    except Exception:
        logger.exception("TAS allocation check failed for %s", normalized_username)
        return current_role

    if not has_allocation:
        return current_role

    try:
        with SessionLocal() as db:
            UserRoleRepository(db).upsert_role(normalized_username, UserRoleEnum.USER.value)
    except Exception:
        logger.exception("Failed to persist TAS-elevated role for %s", normalized_username)
        return current_role

    logger.info(
        "Elevated %s to USER via TAS allocation %s",
        normalized_username,
        settings.PRIMARY_ALLOCATION_CHARGE_CODE,
    )
    return UserRoleEnum.USER.value


def _role_allows(role: str | None, minimum: str) -> bool:
    current_rank = ROLE_RANK.get(normalize_role_value(role, default=UserRoleEnum.NONE), -1)
    required_rank = ROLE_RANK.get(normalize_role_value(minimum, default=UserRoleEnum.NONE), -1)
    return current_rank >= required_rank


# Async function to get the current user based on the provided OAuth2 token
async def get_current_user(token: str | None = Depends(oauth2_scheme)) -> User:
    if settings.ENV == "dev":
        return User(
            username="test",
            role=_default_role(),
        )
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Try internal HS256 JWT first.
    try:
        user_dict = unhash(token)
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
    except jwt.InvalidTokenError:
        pass

    # Fall back to Tapis RS256 JWT verification.
    # See https://tapis.readthedocs.io/en/latest/technical/authentication.html#id2
    if tapis_token_verifier is not None:
        try:
            claims = tapis_token_verifier.verify(token)
            username = TapisTokenVerifier.username_from_claims(claims)
            if username:
                role = resolve_user_role(username, token)
                logger.info("Tapis JWT authentication succeeded for username=%s", username)
                return User(username=username, role=role)
        except Exception as exc:
            logger.debug("Tapis JWT verification failed: %s", exc)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
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
    logger.info(
        "Optional Tapis token header lookup extra=%s",
        {
            "x_tapis_token_present": bool(x_tapis_token),
            "authorization_present": bool(authorization),
            "authorization_is_bearer": bool(authorization and authorization.lower().startswith("bearer ")),
        },
    )
    if x_tapis_token:
        logger.debug("Resolved optional Tapis token from X-TAPIS-TOKEN header")
        return x_tapis_token

    if authorization and authorization.lower().startswith("bearer "):
        logger.debug("Resolved optional Tapis token from Authorization bearer header")
        return authorization.split(" ", 1)[1]

    logger.debug("No optional Tapis token found in request headers")
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
