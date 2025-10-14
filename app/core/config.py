from pydantic_settings import BaseSettings
from pydantic import ConfigDict

class Settings(BaseSettings):
    POSTGRES_PASSWORD: str
    TAS_USER: str
    TAS_SECRET: str
    JWT_SECRET: str
    TAS_URL: str
    DATABASE_URL: str
    ENV: str
    ENVIRONMENT: str
    ALG: str

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"  # Ignore extra fields from .env (like dev-only settings)
    )

def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]