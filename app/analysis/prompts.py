"""Prompt template loading & rendering (Jinja2, versioned filenames).

Template file format: two blocks separated by ``<<<SYSTEM>>>`` / ``<<<USER>>>`` markers.
Filename ``{strategy}_v{n}.md`` parses into (strategy, prompt_version).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Tuple

from jinja2 import Environment, StrictUndefined

from app.core.config import PROJECT_ROOT

PROMPTS_DIR = PROJECT_ROOT / "prompts"
_VERSION_RE = re.compile(r"^(?P<strategy>[a-z_]+)_v(?P<version>\d+)\.md$")


def parse_prompt_version(filename: str) -> Tuple[str, str]:
    m = _VERSION_RE.match(filename)
    if not m:
        raise ValueError("prompt 文件名必须形如 {strategy}_v{n}.md: %s" % filename)
    return m.group("strategy"), "v%s" % m.group("version")


def load_prompt(prompt_file: str) -> Tuple[str, str]:
    """Returns (system_template, user_template)."""
    path = PROMPTS_DIR / prompt_file
    text = path.read_text(encoding="utf-8")
    parts = text.split("<<<USER>>>", 1)
    if len(parts) != 2:
        raise ValueError("prompt %s 缺少 <<<USER>>> 分隔符" % prompt_file)
    system = parts[0].replace("<<<SYSTEM>>>", "", 1).strip()
    return system, parts[1].strip()


def render_prompt(prompt_file: str, ctx: Dict) -> Tuple[str, str, str]:
    """Returns (system, user, prompt_version)."""
    _, version = parse_prompt_version(prompt_file)
    system_tpl, user_tpl = load_prompt(prompt_file)
    env = Environment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
    return env.from_string(system_tpl).render(**ctx), env.from_string(user_tpl).render(**ctx), version
