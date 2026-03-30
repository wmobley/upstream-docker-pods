from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    POSTGRES_PASSWORD: str = Field(default="test_password")
    TAS_USER: str = Field(default="test_user")
    TAS_SECRET: str = Field(default="test_secret")
    JWT_SECRET: str = Field(default="test_secret")
    TAS_URL: str = Field(default="https://example.com")
    TAPIS_BASE_URL: str = Field(default="https://portals.tapis.io")
    TAPIS_TENANT_ID: str = Field(default="portals")
    TAPIS_ENFORCE_AUTH_IN_DEV: bool = Field(default=False)
    DATABASE_URL: str = Field(default="sqlite:///:memory:")
    ENV: str = Field(default="test")
    ENVIRONMENT: str = Field(default="test")
    ALG: str = Field(default="HS256")
    CKAN_URL: str | None = Field(default=None)
    CKAN_ORGANIZATION: str | None = Field(default=None)
    CKAN_ADMIN_USERNAME: str | None = Field(default="dso_test")
    CKAN_ADMIN_API_KEY: str | None = Field(default=None)
    CKAN_TIMEOUT: int = Field(default=30)
    UI_BASE_URL: str = Field(default="http://127.0.0.1:5173")
    API_BASE_URL: str | None = Field(default="http://127.0.0.1:8000")
    TAPIS_PODS_BASE_URL: str | None = Field(default=None)
    TAPIS_SERVICE_USERNAME: str | None = Field(default=None)
    TAPIS_SERVICE_PASSWORD: str | None = Field(default=None)
    ALLOWED_ALLOCATIONS: list[str] | None = Field(default=None)
    DEFAULT_ADMIN_USERS: list[str] = Field(default_factory=lambda: ["wmobley"])

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"  # Ignore extra fields from .env (like dev-only settings)
    )

def get_settings() -> Settings:
    # BaseSettings pulls values from environment; mypy doesn't understand this constructor
    return Settings()
