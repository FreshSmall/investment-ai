from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import (
    AppCfg,
    ConfigError,
    Settings,
    _resolve_placeholders,
    effective_vault_path,
    load_app_config,
    load_sectors,
)


def test_settings_loads_from_env() -> None:
    s = Settings()
    assert s.db_name == "investment_ai_test"  # conftest 注入的测试库名
    assert s.db_port == 3306


def test_settings_missing_required_raises() -> None:
    s = Settings(db_host="", db_user="", db_password="")
    with pytest.raises(ConfigError, match="db_host"):
        s.validate_required()


def test_placeholder_resolution_env_and_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IAI_TEST_VAR", "from_env")
    assert _resolve_placeholders("${IAI_TEST_VAR:fallback}") == "from_env"
    assert _resolve_placeholders("${IAI_MISSING_VAR:fallback}") == "fallback"
    assert _resolve_placeholders("plain") == "plain"
    assert _resolve_placeholders({"a": ["${IAI_TEST_VAR:x}"]}) == {"a": ["from_env"]}


def test_load_app_config_real_file() -> None:
    cfg = load_app_config()
    assert isinstance(cfg, AppCfg)
    assert cfg.pipeline.lookback_hours == 26
    assert cfg.llm.tiers["L1"].model == "deepseek-flash"  # 当前 .env 为 DeepSeek key（切 GLM 时同步改）
    assert cfg.llm.daily_budget_cny > 0
    assert "cls" in cfg.news_providers


def test_load_app_config_bad_yaml(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("llm: {tiers: [broken", encoding="utf-8")
    with pytest.raises(ConfigError, match="YAML"):
        load_app_config(p)


def test_load_app_config_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="不存在"):
        load_app_config(tmp_path / "nope.yaml")


def test_load_sectors_real_file() -> None:
    sectors = load_sectors()
    assert set(sectors.keys()) == {"ai_semiconductor", "power_energy", "robotics"}
    for key, sec in sectors.sectors.items():
        assert sec.keywords, "行业 %s keywords 非空" % key
        assert sec.render_name
        assert "changelog" in sec.sections


def test_load_sectors_empty_keywords_rejected(tmp_path: Path) -> None:
    p = tmp_path / "s.yaml"
    p.write_text(
        "sectors:\n  x:\n    name: X\n    render_name: X\n    keywords: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="keywords 为空"):
        load_sectors(p)


def test_effective_vault_path_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    app_cfg = AppCfg(vault_path="~/DefaultVault")
    settings = Settings(vault_path=None)
    assert effective_vault_path(app_cfg, settings) == Path("~/DefaultVault").expanduser().resolve()
    settings = Settings(vault_path="/tmp/MyVault")
    assert effective_vault_path(app_cfg, settings) == Path("/tmp/MyVault").resolve()
