"""Knowledge updater (V0.3): apply LLM industry_update SectionDiffs to vault.

Renderer stays a pure function; this module owns the *decision* + *application*
(arch §9.1): read current sections -> engine decides diffs -> section-level
replace + changelog prepend (rolling window, DB retains full history via
analyses rows).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from app.core.config import SectorsCfg
from app.core.log import get_logger
from app.knowledge.renderer import atomic_write, get_section, replace_section
from app.knowledge.sections import INDUSTRY_SECTION_TITLES

# sections the LLM may rewrite (changelog is managed here, not by the LLM)
UPDATABLE_SECTIONS = ["overview", "supply_demand", "catalysts", "risks", "metrics"]
_CHANGELOG_MAX_ROWS = 30
_PLACEHOLDER = "（待首次更新）"


def industry_path(vault: Path, sector_key: str, sectors: SectorsCfg) -> Path:
    return vault / "Industries" / ("%s.md" % sectors.sectors[sector_key].render_name)


def build_section_ctx(vault: Path, sector_key: str, sectors: SectorsCfg) -> List[Dict]:
    """Current bodies of updatable sections (prompt context)."""
    path = industry_path(vault, sector_key, sectors)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return [
        {"name": name, "content": get_section(text, name) or _PLACEHOLDER}
        for name in UPDATABLE_SECTIONS
    ]


def apply_industry_update(
    vault: Path,
    sector_key: str,
    sectors: SectorsCfg,
    update: Dict,
    report_date: str,
) -> Dict[str, int]:
    """Apply one LLM industry_update result. Returns {"sections_changed", "changelog_added"}.

    Invariants: unchanged sections are byte-preserved (LLM content ignored when
    changed=false); changelog rows prepend below the table header; window keeps
    the newest 30 rows; bytes outside sections untouched.
    """
    log = get_logger("updater")
    path = industry_path(vault, sector_key, sectors)
    text = path.read_text(encoding="utf-8") if path.exists() else ""

    changed = 0
    for sec in update.get("sections") or []:
        name = sec.get("name")
        if name not in UPDATABLE_SECTIONS:
            continue
        if not sec.get("changed"):
            continue
        new_body = (sec.get("content") or "").strip()
        if not new_body:
            continue
        text = replace_section(text, name, new_body, as_of=report_date)
        changed += 1

    added = 0
    rows = update.get("changelog_rows") or []
    if rows:
        new_lines = []
        for r in rows[:4]:
            ev = r.get("evidence_event_id", "")
            link = "[[Daily/%s#e%s|%s]]" % (report_date, ev[:4], report_date) if ev else report_date
            change = (r.get("change") or "").replace("|", "/").replace("\n", " ").strip()
            new_lines.append("| %s | %s | %s |" % (report_date, change, link))
        header = "| 日期 | 变化 | 证据 |"
        existing = get_section(text, "changelog") or header
        old_rows = [ln for ln in existing.splitlines() if ln.startswith("|") and ln != header]
        # 同日重跑幂等：先剔除该日期旧行，再 prepend 当日新行（当日变化集整体替换）
        day_prefix = "| %s |" % report_date
        old_rows = [ln for ln in old_rows if not ln.startswith(day_prefix)]
        table = "\n".join([header] + new_lines + old_rows[:_CHANGELOG_MAX_ROWS - len(new_lines)])
        text = replace_section(text, "changelog", table, as_of=report_date)
        added = len(new_lines)

    if changed or added:
        atomic_write(path, text)
        log.info(
            "industry updated",
            extra={"ctx": {"sector": sector_key, "sections": changed, "changelog": added}},
        )
    return {"sections_changed": changed, "changelog_added": added}
