import pytest
from pydantic import ValidationError
from app.core.config import get_settings, Settings
import os
from pathlib import Path

def test_get_settings() -> None:
    settings = get_settings()
    assert isinstance(settings, Settings)
    assert hasattr(settings, 'ENV')
    assert hasattr(settings, 'TAS_URL')
    assert hasattr(settings, 'TAS_USER')
    assert hasattr(settings, 'TAS_SECRET')
    assert hasattr(settings, 'JWT_SECRET')
    assert hasattr(settings, 'ALG')
    assert hasattr(settings, 'TAPIS_BACKUP_SYSTEM_ID')

def test_settings_singleton() -> None:
    settings1 = get_settings()
    settings2 = get_settings()
    assert settings1 == settings2

def test_settings_required_values() -> None:
    settings = get_settings()
    assert settings.TAS_URL is not None
    assert settings.TAS_USER is not None
    assert settings.TAS_SECRET is not None
    assert settings.JWT_SECRET is not None
    assert settings.ALG is not None
    assert settings.POSTGRES_PASSWORD is not None
    assert settings.DATABASE_URL is not None
    assert settings.TAPIS_BACKUP_SYSTEM_ID is not None

def test_settings_jwt_config() -> None:
    settings = get_settings()
    assert isinstance(settings.JWT_SECRET, str)
    assert len(settings.JWT_SECRET) > 0
    assert settings.ALG in ["HS256", "HS384", "HS512"]  # Common JWT algorithms

def test_settings_with_env_sample(monkeypatch):
    # Load .env.sample file
    env_sample_path = Path(__file__).parent.parent.parent / '.env.sample'
    with open(env_sample_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                key, value = line.split('=', 1)
                monkeypatch.setenv(key, value)

    settings = get_settings()

    # Verify values match .env.sample
    assert settings.POSTGRES_PASSWORD == "fastapi_traefik"
    assert settings.TAS_USER == "CHANGE_ME"
    assert settings.TAS_SECRET == "CHANGE_ME"
    assert settings.JWT_SECRET == "test_secret"
    assert settings.ALG == "HS256"
    assert settings.TAS_URL == "https://tas-dev.tacc.utexas.edu/api-test"
    assert settings.ENVIRONMENT == "dev"
    assert settings.ENV == "dev"
    assert settings.DATABASE_URL == "postgresql+psycopg://fastapi_traefik@localhost:5432/fastapi_traefik"
    assert settings.TAPIS_BACKUP_SYSTEM_ID == "ptdatax.project.PTDATAX-284"
    assert settings.TAPIS_BACKUP_ROOT_PATH == "/upstream-postgres"
    assert settings.TAPIS_BACKUP_RETENTION_DAYS == 7


def test_is_primary_instance_defaults_false() -> None:
    settings = get_settings()
    assert settings.IS_PRIMARY_INSTANCE is False
    assert settings.PRIMARY_ALLOCATION_CHARGE_CODE == "PT2050-DataX"


def test_primary_instance_rejects_placeholder_tas_credentials() -> None:
    with pytest.raises(ValidationError):
        Settings(IS_PRIMARY_INSTANCE=True, TAS_USER="test_user", TAS_SECRET="real_secret")
    with pytest.raises(ValidationError):
        Settings(IS_PRIMARY_INSTANCE=True, TAS_USER="real_user", TAS_SECRET="test_secret")


def test_primary_instance_accepts_real_tas_credentials() -> None:
    settings = Settings(IS_PRIMARY_INSTANCE=True, TAS_USER="real_user", TAS_SECRET="real_secret")
    assert settings.IS_PRIMARY_INSTANCE is True
