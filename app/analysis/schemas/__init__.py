"""Schema loading (with dynamic sector-enum injection), tolerant JSON parsing, validation.

- ``__SECTORS__`` placeholder in schema enums is replaced by real sector keys from
  sectors.yaml at validation time — hallucinated industry names get rejected here.
- ``parse_llm_json`` strips markdown fences / BOM / trailing commas before json.loads.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from jsonschema import Draft7Validator

_SCHEMA_DIR = Path(__file__).resolve().parent
_SECTOR_PLACEHOLDER = "__SECTORS__"
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


class ParseError(Exception):
    """LLM output could not be parsed into a JSON object."""


def parse_llm_json(text: Any) -> Dict[str, Any]:
    """dict passthrough; str gets fence-stripped, BOM-trimmed, trailing-comma-recovered."""
    if isinstance(text, dict):
        return text
    if not isinstance(text, str) or not text.strip():
        raise ParseError("空响应")
    raw = text.strip().lstrip("\ufeff")
    fenced = _FENCE_RE.search(raw)
    if fenced:
        raw = fenced.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        recovered = _TRAILING_COMMA_RE.sub(r"\1", raw)
        try:
            data = json.loads(recovered)
        except json.JSONDecodeError as e:
            raise ParseError("JSON 解析失败: %s（前100字符: %s）" % (e, raw[:100]))
    if not isinstance(data, dict):
        raise ParseError("顶层必须是对象，实际是 %s" % type(data).__name__)
    return data


def load_schema(name: str, sector_keys: Optional[List[str]] = None) -> Dict[str, Any]:
    path = _SCHEMA_DIR / ("%s.schema.json" % name)
    schema = json.loads(path.read_text(encoding="utf-8"))
    if sector_keys:
        schema = _inject_sectors(schema, sector_keys)
    return schema


def _inject_sectors(node: Any, keys: List[str]) -> Any:
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k == "enum" and isinstance(v, list) and _SECTOR_PLACEHOLDER in v:
                out[k] = keys
            else:
                out[k] = _inject_sectors(v, keys)
        return out
    if isinstance(node, list):
        return [_inject_sectors(x, keys) for x in node]
    return node


def validate(
    schema_name: str, data: Dict[str, Any], sector_keys: Optional[List[str]] = None
) -> Tuple[bool, List[str]]:
    schema = load_schema(schema_name, sector_keys)
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if not errors:
        return True, []
    msgs = []
    for e in errors[:5]:
        path = "/".join(str(p) for p in e.absolute_path) or "<root>"
        msgs.append("%s: %s" % (path, e.message))
    return False, msgs
