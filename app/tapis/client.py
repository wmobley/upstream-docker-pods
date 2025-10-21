import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, cast

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

        access_token = getattr(access_token_obj, "access_token", None)
        refresh_token = getattr(refresh_token_obj, "refresh_token", None)
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
            access_token = access_token or token_payload.get("access_token")
            refresh_token = refresh_token or token_payload.get("refresh_token")
            expires_at = expires_at or token_payload.get("expires_at")

            if not access_token:
                try:
                    result = cast(Dict[str, Any], token_payload.get("result", {}) or {})
                    token_info = result.get("token_info", {}) if isinstance(result, dict) else {}
                    access_token = token_info.get("access_token")
                    refresh_token = refresh_token or token_info.get("refresh_token")
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
            access_token = getattr(access_token_obj, "access_token", access_token)
            expires_at = expires_at or getattr(access_token_obj, "expires_at", None)
        if not refresh_token and hasattr(client, "refresh_token"):
            refresh_token_obj = getattr(client, "refresh_token")
            refresh_token = getattr(refresh_token_obj, "refresh_token", refresh_token)
            expires_at = expires_at or getattr(refresh_token_obj, "expires_at", None)

        if not access_token:
            logger.info(
                "Tapis authentication succeeded but no access_token returned for %s",
                username,
            )
            return TapisAuthOutcome(tokens=None, error="access_token missing from Tapis response")

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
