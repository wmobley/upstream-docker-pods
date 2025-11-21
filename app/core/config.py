from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    POSTGRES_PASSWORD: str = Field(default="test_password")
    TAS_USER: str = Field(default="test_user")
    TAS_SECRET: str = Field(default="test_secret")
    JWT_SECRET: str = Field(default="test_secret")
    TAS_URL: str = Field(default="https://example.com")
    TAPIS_BASE_URL: str = Field(default="https://tacc.tapis.io")
    TAPIS_TENANT_ID: str = Field(default="tacc")
    TAPIS_ENFORCE_AUTH_IN_DEV: bool = Field(default=False)
    DATABASE_URL: str = Field(default="sqlite:///:memory:")
    ENV: str = Field(default="test")
    ENVIRONMENT: str = Field(default="test")
    ALG: str = Field(default="HS256")
    CKAN_URL: str | None = Field(default=None)
    CKAN_ORGANIZATION: str | None = Field(default=None)
    CKAN_TIMEOUT: int = Field(default=30)
    UI_BASE_URL: str = Field(default="http://127.0.0.1:5173")
    API_BASE_URL: str | None = Field(default="http://127.0.0.1:8000")
    ALLOWED_ALLOCATIONS: list[str] | None = Field(default=None)
    TAPIS_PODS_BASE_URL: str | None = Field(default=None)
    TAPIS_POD_ID: str | None = Field(default=None)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"  # Ignore extra fields from .env (like dev-only settings)
    )

def get_settings() -> Settings:
    # BaseSettings pulls values from environment; mypy doesn't understand this constructor
    return Settings()
