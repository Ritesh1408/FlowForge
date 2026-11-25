import pytest
from pydantic import ValidationError

from flowforge.core.config import Settings

_ENV_VARS = (
    "DATABASE_URL",
    "TEST_DATABASE_URL",
    "REDIS_URL",
    "APP_ENV",
    "LOG_LEVEL",
    "HEALTH_CHECK_TIMEOUT_SECONDS",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_loads_from_environment_with_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/flowforge")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    settings = Settings(_env_file=None)

    assert settings.database_url.get_secret_value().endswith("/flowforge")
    assert settings.redis_url.get_secret_value() == "redis://localhost:6379/0"
    assert settings.test_database_url is None
    assert settings.app_env == "development"
    assert settings.log_level == "INFO"
    assert settings.health_check_timeout_seconds == 2.0


def test_loads_from_env_file(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql+asyncpg://u:p@localhost:5432/flowforge\n"
        "TEST_DATABASE_URL=postgresql+asyncpg://u:p@localhost:5432/flowforge_test\n"
        "REDIS_URL=redis://localhost:6379/0\n"
        "LOG_LEVEL=debug\n"
        "HEALTH_CHECK_TIMEOUT_SECONDS=0.5\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.test_database_url is not None
    assert settings.test_database_url.get_secret_value().endswith("/flowforge_test")
    assert settings.log_level == "DEBUG"
    assert settings.health_check_timeout_seconds == 0.5


def test_secrets_are_masked() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://user:db-pass-123@localhost/flowforge",
        test_database_url="postgresql+asyncpg://user:db-pass-123@localhost/flowforge_test",
        redis_url="redis://:redis-pass-456@localhost:6379/0",
    )

    for rendered in (repr(settings), str(settings), str(settings.model_dump())):
        assert "db-pass-123" not in rendered
        assert "redis-pass-456" not in rendered


def test_missing_required_urls_fail() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    ("field", "value"),
    [("log_level", "LOUD"), ("health_check_timeout_seconds", 0), ("app_env", "staging")],
)
def test_invalid_values_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql+asyncpg://u:p@localhost/flowforge",
            redis_url="redis://localhost:6379/0",
            **{field: value},
        )
