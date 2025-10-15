from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    POSTGRES_PASSWORD: str = Field(default="test_password")
    TAS_USER: str = Field(default="test_user")
    TAS_SECRET: str = Field(default="test_secret")
    JWT_SECRET: str = Field(default="test_secret")
    TAS_URL: str = Field(default="https://example.com")
    DATABASE_URL: str = Field(default="sqlite:///:memory:")
    ENV: str = Field(default="test")
    ENVIRONMENT: str = Field(default="test")
    ALG: str = Field(default="HS256")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"  # Ignore extra fields from .env (like dev-only settings)
    )

def get_settings() -> Settings:
    # BaseSettings pulls values from environment; mypy doesn't understand this constructor
    return Settings()
