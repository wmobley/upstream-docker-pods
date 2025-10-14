"""
Development middleware to emulate Tapis authentication headers.

This middleware is ONLY active in development mode and allows testing
Tapis authentication without actually running in a Tapis Pod.

Usage:
    Set ENABLE_DEV_TAPIS_HEADERS=true in your .env file
    Configure test headers via environment variables or use defaults
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.config import get_settings
import os


class DevTapisHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to inject Tapis headers in development mode.

    Only active when:
    - ENV=dev
    - ENABLE_DEV_TAPIS_HEADERS=true

    Injects headers if they're not already present in the request.
    """

    def __init__(self, app):
        super().__init__(app)
        self.settings = get_settings()

        # Check if dev headers are enabled
        self.enabled = (
            self.settings.ENV == "dev" and
            os.getenv("ENABLE_DEV_TAPIS_HEADERS", "false").lower() == "true"
        )

        # Get test header values from environment or use defaults
        self.test_username = os.getenv("DEV_TAPIS_USERNAME", "testuser")
        self.test_tenant = os.getenv("DEV_TAPIS_TENANT", "tacc")
        self.test_site = os.getenv("DEV_TAPIS_SITE", "tacc")
        self.test_internal = os.getenv(
            "DEV_TAPIS_INTERNAL",
            f"{self.test_username}.{self.test_tenant}.{self.test_site}"
        )

    async def dispatch(self, request: Request, call_next):
        if self.enabled:
            # Create a mutable headers object
            headers = dict(request.headers)

            # Only inject if not already present (allows manual override)
            if "x-tapis-username" not in headers:
                headers["x-tapis-username"] = self.test_username

            if "x-tapis-tenant" not in headers:
                headers["x-tapis-tenant"] = self.test_tenant

            if "x-tapis-site" not in headers:
                headers["x-tapis-site"] = self.test_site

            if "internal" not in headers:
                headers["internal"] = self.test_internal

            # Update request headers
            request._headers = headers
            request.scope["headers"] = [
                (k.lower().encode(), v.encode()) for k, v in headers.items()
            ]

        response = await call_next(request)
        return response
