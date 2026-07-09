import logging
import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar, Dict, Optional, cast

import jwt
import requests
from tapipy.errors import BaseTapyException  # type: ignore[import-untyped]
from tapipy.tapis import Tapis  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False


@dataclass(slots=True)
class TapisAuthOutcome:
    tokens: Optional[Dict[str, Any]]
    error: Optional[str] = None


@dataclass(slots=True)
class TapisAuthClient:
    """Lightweight wrapper around the tapipy ``Tapis`` client for user auth."""

    base_url: str
    tenant_id: str

    @staticmethod
    def _token_summary(token: Any) -> str:
        if not isinstance(token, str) or not token:
            return "missing"
        dots = token.count(".")
        return f"len={len(token)} dots={dots} prefix={token[:12]} suffix={token[-12:]}"

    @classmethod
    def _coerce_token_string(cls, value: Any, *, token_key: str) -> Optional[str]:
        if value is None:
            return None

        if isinstance(value, str):
            candidate = value.strip()
            if candidate.lower().startswith("bearer "):
                candidate = candidate.split(" ", 1)[1].strip()
            if candidate.startswith('"') and candidate.endswith('"'):
                candidate = candidate[1:-1].strip()
            if candidate.startswith("{") and candidate.endswith("}"):
                try:
                    parsed = json.loads(candidate)
                except Exception:
                    return candidate or None
                return cls._coerce_token_string(parsed, token_key=token_key)
            return candidate or None

        if isinstance(value, dict):
            for key in (token_key, "token", "access_token", "refresh_token"):
                if key in value:
                    return cls._coerce_token_string(value.get(key), token_key=token_key)
            return None

        for attr in (token_key, "token", "access_token", "refresh_token"):
            if hasattr(value, attr):
                nested = getattr(value, attr, None)
                if nested is not None and nested is not value:
                    return cls._coerce_token_string(nested, token_key=token_key)

        return None

    def authenticate(self, username: str, password: str) -> TapisAuthOutcome:
        """
        Validate user credentials against the configured Tapis tenant.

        Returns a dictionary of Tapis tokens when authentication succeeds. If
        authentication fails the method returns ``None`` along with the error
        message, if one is available.
        """
        logger.debug(
            "Requesting Tapis tokens for username=%s tenant=%s base_url=%s",
            username,
            self.tenant_id,
            self.base_url,
        )
        try:
            client = Tapis(
                base_url=self.base_url,
                tenant_id=self.tenant_id,
                username=username,
                password=password,
            )
            client.get_tokens()
        except BaseTapyException as exc:  # pragma: no cover - dependency behaviour
            logger.info(
                "Tapis authentication failed for user %s: %s (status=%s, args=%s)",
                username,
                exc,
                getattr(exc, "status_code", None),
                getattr(exc, "args", None),
            )
            error_message = getattr(exc, "message", None) or str(exc)
            response_obj = getattr(exc, "response", None)
            if response_obj is not None:
                response_repr = getattr(response_obj, "text", None) or response_obj
                logger.info("Raw Tapis response for %s: %s", username, response_repr)
            parsed_content = getattr(exc, "parsed_content", None)
            if parsed_content:
                logger.info("Parsed Tapis error payload for %s: %s", username, parsed_content)
            return TapisAuthOutcome(tokens=None, error=error_message)
        except Exception:  # pragma: no cover - defensive guard
            logger.exception(
                "Unexpected error while authenticating %s against Tapis",
                username,
            )
            raise

        # Tapipy exposes token helper objects on the client. Capture those first.
        access_token_obj = getattr(client, "access_token", None)
        refresh_token_obj = getattr(client, "refresh_token", None)
        service_token_obj = getattr(client, "service_token", None)

        access_token = self._coerce_token_string(getattr(access_token_obj, "access_token", None), token_key="access_token")
        refresh_token = self._coerce_token_string(getattr(refresh_token_obj, "refresh_token", None), token_key="refresh_token")
        expires_at = getattr(access_token_obj, "expires_at", None)

        def log_token_obj(name: str, obj: Any) -> None:
            logger.debug(
                "Tapis %s object for %s: %s",
                name,
                username,
                getattr(obj, "__dict__", obj),
            )

        if access_token_obj is not None:
            log_token_obj("access_token", access_token_obj)
        if refresh_token_obj is not None:
            log_token_obj("refresh_token", refresh_token_obj)
        if service_token_obj is not None:
            log_token_obj("service_token", service_token_obj)

        token_payload = getattr(client, "token", None)
        if token_payload:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Full token payload for %s: %s",
                    username,
                    token_payload,
                )
            else:
                logger.info(
                    "Token payload keys for %s: %s",
                    username,
                    list(token_payload.keys()),
                )
            access_token = access_token or self._coerce_token_string(token_payload.get("access_token"), token_key="access_token")
            refresh_token = refresh_token or self._coerce_token_string(token_payload.get("refresh_token"), token_key="refresh_token")
            expires_at = expires_at or token_payload.get("expires_at")

            if not access_token:
                try:
                    result = cast(Dict[str, Any], token_payload.get("result", {}) or {})
                    token_info = result.get("token_info", {}) if isinstance(result, dict) else {}
                    access_token = self._coerce_token_string(token_info.get("access_token"), token_key="access_token")
                    refresh_token = refresh_token or self._coerce_token_string(token_info.get("refresh_token"), token_key="refresh_token")
                    expires_at = expires_at or token_info.get("expires_at")
                except AttributeError:
                    access_token = None
        else:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Tapis authentication succeeded but no token payload returned for %s. Raw client dict: %s",
                    username,
                    getattr(client, "__dict__", "unavailable"),
                )
            else:
                logger.info(
                    "Tapis authentication succeeded but no token payload returned for %s.",
                    username,
                )

        # Final fallback: tapipy keeps the JWTs on the access/refresh token objects.
        if not access_token and hasattr(client, "access_token"):
            access_token_obj = getattr(client, "access_token")
            access_token = self._coerce_token_string(getattr(access_token_obj, "access_token", access_token), token_key="access_token")
            expires_at = expires_at or getattr(access_token_obj, "expires_at", None)
        if not refresh_token and hasattr(client, "refresh_token"):
            refresh_token_obj = getattr(client, "refresh_token")
            refresh_token = self._coerce_token_string(getattr(refresh_token_obj, "refresh_token", refresh_token), token_key="refresh_token")
            expires_at = expires_at or getattr(refresh_token_obj, "expires_at", None)

        logger.info(
            "Tapis token extraction summary for %s: access=%s refresh=%s",
            username,
            self._token_summary(access_token),
            self._token_summary(refresh_token),
        )

        if not access_token:
            logger.info(
                "Tapis authentication succeeded but no access_token returned for %s",
                username,
            )
            return TapisAuthOutcome(tokens=None, error="access_token missing from Tapis response")

        if access_token.count(".") != 2:
            logger.warning(
                "Tapis authentication returned malformed access_token for %s: %s",
                username,
                self._token_summary(access_token),
            )
            return TapisAuthOutcome(tokens=None, error="Malformed access_token returned from Tapis")

        def coerce_expiration(value: Any) -> Optional[int]:
            if value is None:
                return None
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, datetime):
                return int(value.timestamp())
            if isinstance(value, str):
                try:
                    normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
                    return int(datetime.fromisoformat(normalized).timestamp())
                except ValueError:
                    logger.debug("Unable to parse expires_at string from Tapis: %s", value)
                    return None
            return None

        return TapisAuthOutcome(
            tokens={
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": coerce_expiration(expires_at),
            }
        )


class TapisTokenVerifier:
    """Verify RS256-signed Tapis JWTs using the tenant's public key.

    The public key is fetched from the Tenants API and cached for _KEY_TTL seconds.
    See https://tapis.readthedocs.io/en/latest/technical/authentication.html#id2
    """

    _KEY_TTL: ClassVar[float] = 3600.0  # re-fetch public key after 1 hour

    def __init__(self, base_url: str, tenant_id: str) -> None:
        self.base_url = base_url
        self.tenant_id = tenant_id
        self._public_key: Optional[str] = None
        self._key_fetched_at: float = 0.0

    def _fetch_public_key(self) -> str:
        url = f"{self.base_url.rstrip('/')}/v3/tenants/{self.tenant_id}"
        logger.debug("Fetching Tapis public key from %s", url)
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result") or data
        public_key: Optional[str] = result.get("public_key") if isinstance(result, dict) else None
        if not public_key:
            raise ValueError(f"No public_key in tenant response for {self.tenant_id}")
        logger.info("Fetched Tapis public key for tenant=%s", self.tenant_id)
        return public_key

    def _get_public_key(self) -> str:
        now = time.monotonic()
        if self._public_key is None or (now - self._key_fetched_at) > self._KEY_TTL:
            self._public_key = self._fetch_public_key()
            self._key_fetched_at = now
        return self._public_key

    def verify(self, token: str) -> Dict[str, Any]:
        """Decode and verify a Tapis RS256 JWT. Raises jwt.InvalidTokenError on failure."""
        public_key = self._get_public_key()
        return cast(Dict[str, Any], jwt.decode(token, public_key, algorithms=["RS256"]))

    @staticmethod
    def username_from_claims(claims: Dict[str, Any]) -> Optional[str]:
        """Extract the Tapis username from decoded JWT claims."""
        username = claims.get("tapis/username")
        if username:
            return str(username)
        sub = claims.get("sub", "")
        if sub and "@" in sub:
            return sub.split("@")[0]
        return str(sub) if sub else None
