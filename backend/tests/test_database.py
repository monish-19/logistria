from __future__ import annotations

from app.models import normalize_database_url


def test_postgres_urls_use_psycopg_driver() -> None:
    assert normalize_database_url("postgresql://user:pass@host/db") == (
        "postgresql+psycopg://user:pass@host/db"
    )


def test_sqlite_urls_are_unchanged() -> None:
    assert normalize_database_url("sqlite:///:memory:") == "sqlite:///:memory:"
