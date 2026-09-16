from __future__ import annotations

from sqlalchemy.engine import URL

from app.core.config import Settings
from app.db.engine import build_database_url


def test_url_construction_encodes_special_password() -> None:
    s = Settings(
        db_host="rds.example.com",
        db_port=3306,
        db_user="app",
        db_password="p@ss:word/123",
        db_name="investment_ai_test",
    )
    url: URL = build_database_url(s)
    assert url.drivername == "mysql+pymysql"
    assert url.database == "investment_ai_test"
    assert url.username == "app"
    assert url.password == "p@ss:word/123"  # 原值保留（密码含 @ 不会泄进 host）
    assert url.query["charset"] == "utf8mb4"
    rendered = url.render_as_string(hide_password=False)
    assert "rds.example.com" in rendered
    assert "p%40ss" in rendered  # 转义后可安全用于 DSN


def test_url_uses_test_db_from_conftest_env() -> None:
    from app.core.config import get_settings

    url = build_database_url(get_settings())
    assert url.database == "investment_ai_test"
