import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import make_url
from alembic.config import Config

from app.core.config import BACKEND_DIR, ENV_FILE, Settings, resolve_database_url


REPOSITORY_ROOT = BACKEND_DIR.parent
EXPECTED_DATABASE = BACKEND_DIR / "smartroster.db"


def run_settings_from(directory: Path, **environment: str) -> str:
    code = (
        "from app.core.config import get_settings; "
        "print(get_settings().database_url)"
    )
    env = os.environ.copy()
    env.pop("BACKEND_DATABASE_URL", None)
    env["PYTHONPATH"] = str(BACKEND_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    env.update(environment)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=directory,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_settings_use_backend_env_file_and_database_path():
    settings = Settings(_env_file=ENV_FILE)

    assert ENV_FILE == BACKEND_DIR / ".env"
    assert settings.database_url == resolve_database_url("sqlite:///./smartroster.db")
    assert make_url(settings.database_url).database == str(EXPECTED_DATABASE)


def test_root_and_backend_launches_resolve_the_same_database():
    root_url = run_settings_from(REPOSITORY_ROOT)
    backend_url = run_settings_from(BACKEND_DIR)

    assert root_url == backend_url
    assert make_url(root_url).database == str(EXPECTED_DATABASE)


def test_explicit_sqlite_url_is_resolved_without_changing_non_sqlite_urls():
    explicit = resolve_database_url("sqlite:///./custom-test.db")

    assert make_url(explicit).database == str(BACKEND_DIR / "custom-test.db")
    assert resolve_database_url("postgresql+psycopg://user:pass@host/db") == (
        "postgresql+psycopg://user:pass@host/db"
    )


def test_standard_postgres_urls_use_the_installed_psycopg_driver():
    assert resolve_database_url("postgresql://user:pass@host/db") == (
        "postgresql+psycopg://user:pass@host/db"
    )
    assert resolve_database_url("postgres://user:pass@host/db") == (
        "postgresql+psycopg://user:pass@host/db"
    )


def test_alembic_config_preserves_percent_encoded_database_password():
    database_url = (
        "postgresql+psycopg://postgres.project:pa%40ss%25word@pooler.example:5432/postgres"
    )
    config = Config()

    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

    assert config.get_main_option("sqlalchemy.url") == database_url


def test_alembic_and_application_share_settings_database_url():
    source = (BACKEND_DIR / "alembic" / "env.py").read_text(encoding="utf-8")

    assert "get_settings().database_url" in source
    assert Settings().database_url == resolve_database_url("sqlite:///./smartroster.db")
