from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_TABLES = ("pods", "employees", "brands", "processes", "public_holidays", "rosters")


def _run_alembic(database: Path, *args: str) -> None:
    env = os.environ.copy()
    env["BACKEND_DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
    env["PYTHONPATH"] = str(BACKEND_DIR)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR, env=env,
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_fresh_database_migrates_and_seeds_idempotently(tmp_path: Path):
    database = tmp_path / "fresh.sqlite"
    _run_alembic(database, "upgrade", "head")

    connection = sqlite3.connect(database)
    org_id, = connection.execute(
        "SELECT id FROM organizations WHERE name = 'Demo Operations'"
    ).fetchone()
    for table in ROOT_TABLES:
        columns = {row[1]: row for row in connection.execute(f"PRAGMA table_info({table})")}
        assert columns["organization_id"][3] == 1
        assert connection.execute(
            f"SELECT count(*) FROM {table} WHERE organization_id != ?", (org_id,)
        ).fetchone()[0] == 0
    connection.close()

    env = os.environ.copy()
    env["BACKEND_DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
    env["PYTHONPATH"] = str(BACKEND_DIR)
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-m", "scripts.seed_demo"], cwd=BACKEND_DIR, env=env,
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    connection = sqlite3.connect(database)
    assert connection.execute("SELECT count(*) FROM organizations").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM employees").fetchone()[0] == 30
    assert connection.execute(
        "SELECT count(*) FROM employees WHERE organization_id = ?", (org_id,)
    ).fetchone()[0] == 30
    connection.close()


def test_existing_organization_and_root_record_are_preserved(tmp_path: Path):
    database = tmp_path / "existing.sqlite"
    _run_alembic(database, "upgrade", "7c3d8e1a2b4f")
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO organizations (id, name, is_active, created_at, updated_at) "
        "VALUES (41, 'Demo Operations', 1, '2026-01-01', '2026-01-01')"
    )
    connection.execute(
        "INSERT INTO pods (id, code, name, is_active, created_at, updated_at) "
        "VALUES (73, 'EXISTING', 'Existing Pod', 1, '2026-01-01', '2026-01-01')"
    )
    connection.commit()
    connection.close()

    _run_alembic(database, "upgrade", "head")
    connection = sqlite3.connect(database)
    assert connection.execute("SELECT id FROM organizations").fetchall() == [(41,)]
    assert connection.execute(
        "SELECT id, organization_id FROM pods WHERE id = 73"
    ).fetchone() == (73, 41)
    connection.close()

