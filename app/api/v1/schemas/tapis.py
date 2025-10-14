from pydantic import BaseModel, Field
from typing import Optional


class TapisUser(BaseModel):
    """User model from Tapis authentication headers."""
    username: str = Field(..., description="Tapis username from X-Tapis-Username header")
    tenant: str = Field(..., description="Tapis tenant ID from X-Tapis-Tenant header")
    site: str = Field(..., description="Tapis site ID from X-Tapis-Site header")
    internal: Optional[str] = Field(None, description="Internal identifier in format username.tenant.site")

    @property
    def full_identifier(self) -> str:
        """Returns the full Tapis identifier in format username.tenant.site"""
        return f"{self.username}.{self.tenant}.{self.site}"
