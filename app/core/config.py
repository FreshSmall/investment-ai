"""Typed configuration: .env secrets via pydantic-settings, runtime params via YAML.

Layering (architecture §13):
- ``Settings``  -> credentials & env (.env, never committed)
- ``AppCfg``    -> config/settings.yaml (models, budget, pipeline params, vault path)
- ``SectorsCfg``-> config/sectors.yaml (industry keywords, the ONLY source of sector words)

Placeholder syntax in YAML: ``${VAR:default}`` resolved against environment variables.
"""

from __future__ import annotations

import functools
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

_PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)(?::([^}]*))?\}")


class ConfigError(Exception):
    """Raised when configuration is missing or invalid (fail fast at startup)."""


class Settings(BaseSettings):
    """Secrets from .env / environment. No business defaults live here."""

    db_host: str = ""
    db_port: int = 3306
    db_user: str = ""
    db_password: str = ""
    db_name: str = "investment_ai"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    vault_path: Optional[str] = None  # env IAI_VAULT_PATH overrides YAML

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def validate_required(self) -> None:
        missing = [
            name
            for name in ("db_host", "db_user", "db_password")
            if not getattr(self, name)
        ]
        if missing:
            raise ConfigError(
                "缺少必需配置: %s —— 请检查 .env（参考 .env.example）" % ", ".join(missing)
            )


class PriceCfg(BaseModel):
    input_per_m: float = 0.0
    output_per_m: float = 0.0


class ModelTierCfg(BaseModel):
    model: str
    temperature: float = 0.3
    max_tokens: int = 2000


class PipelineCfg(BaseModel):
    lookback_hours: int = 26
    classify_batch_size: int = 20
    watchdog_minutes: int = 30
    llm_timeout_seconds: int = 60
    daily_p1_cap: int = 30            # 日报渲染 P1 条数上限（P0 不设限）
    l0_min_content_hits: int = 2      # 正文-only 命中需 ≥N 个不同行业关键词
    near_dup_hours: int = 48          # 同题归并回看窗口
    near_dup_jaccard: float = 0.6     # 标题 bigram Jaccard 阈值
    near_dup_lcs_chars: int = 10      # 最长公共子串阈值（防定期栏目误合并）
    run_gate_max_per_hour: int = 8    # 兜底频率门：近 1 小时 run 数上限，超限 blocked（正常 2/天）
    run_gate_max_per_day: int = 20    # 兜底频率门：当日 run 数上限（含 weekly 与手动重跑）


class LlmCfg(BaseModel):
    tiers: Dict[str, ModelTierCfg]
    prices: Dict[str, PriceCfg] = Field(default_factory=dict)
    daily_budget_cny: float = 10.0
    min_call_interval_seconds: float = 0.0

    def price_of(self, model: str) -> PriceCfg:
        return self.prices.get(model, PriceCfg())


class AppCfg(BaseModel):
    vault_path: str = "~/Investment-KB"
    news_providers: List[str] = Field(default_factory=lambda: ["cls", "eastmoney"])
    pipeline: PipelineCfg = Field(default_factory=PipelineCfg)
    llm: LlmCfg = Field(default_factory=lambda: LlmCfg(tiers={}))


class SectorCfg(BaseModel):
    name: str
    render_name: str
    keywords: List[str]
    sections: List[str] = Field(default_factory=list)


class SectorsCfg(BaseModel):
    sectors: Dict[str, SectorCfg]

    def keys(self) -> List[str]:
        return list(self.sectors.keys())

    def all_keywords(self) -> List[str]:
        out: List[str] = []
        for s in self.sectors.values():
            out.extend(s.keywords)
        return out


def _resolve_placeholders(value: Any) -> Any:
    if isinstance(value, str):
        def repl(m: "re.Match[str]") -> str:
            var, default = m.group(1), m.group(2)
            env_val = os.environ.get(var, "")
            return env_val if env_val else (default or "")

        return _PLACEHOLDER.sub(repl, value)
    if isinstance(value, dict):
        return {k: _resolve_placeholders(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_placeholders(v) for v in value]
    return value


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise ConfigError("配置文件不存在: %s" % path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError("YAML 解析失败: %s (%s)" % (path, e))
    if not isinstance(data, dict):
        raise ConfigError("YAML 顶层必须是映射: %s" % path)
    return _resolve_placeholders(data)


def load_app_config(path: Optional[Path] = None) -> AppCfg:
    raw = _load_yaml(path or CONFIG_DIR / "settings.yaml")
    try:
        return AppCfg(**raw)
    except Exception as e:  # pydantic ValidationError etc.
        raise ConfigError("settings.yaml 结构非法: %s" % e)


def load_sectors(path: Optional[Path] = None) -> SectorsCfg:
    raw = _load_yaml(path or CONFIG_DIR / "sectors.yaml")
    try:
        cfg = SectorsCfg(**raw)
    except Exception as e:
        raise ConfigError("sectors.yaml 结构非法: %s" % e)
    for key, sec in cfg.sectors.items():
        if not sec.keywords:
            raise ConfigError("行业 %s 的 keywords 为空" % key)
    return cfg


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@functools.lru_cache(maxsize=1)
def get_app_config() -> AppCfg:
    return load_app_config()


@functools.lru_cache(maxsize=1)
def get_sectors() -> SectorsCfg:
    return load_sectors()


def reset_config_cache() -> None:
    """Test hook: clear cached config after mutating env/files."""
    get_settings.cache_clear()
    get_app_config.cache_clear()
    get_sectors.cache_clear()


def effective_vault_path(app_cfg: AppCfg, settings: Settings) -> Path:
    raw = settings.vault_path or app_cfg.vault_path
    return Path(raw).expanduser().resolve()
