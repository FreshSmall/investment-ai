"""Deterministic Obsidian renderer + SECTION protocol (arch §9).

Invariants:
- Rendering is a PURE function of its input model — same input, same bytes
  (this is what makes re-runs and `render --all` safe).
- Only content between ``IAI:SECTION:name`` markers is ever rewritten;
  anything outside (human notes) is preserved byte-for-byte.
- Writes are atomic: tmp file + rename.
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from app.core.config import SectorsCfg
from app.knowledge.sections import (
    DIRECTION_BADGES,
    INDUSTRY_SECTION_TITLES,
    THESIS_SECTION_TITLES,
    THESIS_STATUS_BADGES,
)
from app.core.log import get_logger

_START_RE = re.compile(
    r"<!-- IAI:SECTION:(?P<name>[a-z_]+) START[^>]*-->\n?(?P<body>.*?)\n?<!-- IAI:SECTION:\2 END -->\n?",
    re.DOTALL,
)


def anchor(event_id: str) -> str:
    return "e" + event_id[:4]


def replace_section(text: str, name: str, new_body: str, version: int = 1, as_of: str = "") -> str:
    """Replace one section's body; bytes outside every section are untouched."""
    marker_start = "<!-- IAI:SECTION:%s START (v%s%s) -->\n" % (name, version, ", " + as_of if as_of else "")
    marker_end = "\n<!-- IAI:SECTION:%s END -->" % name
    replacement = marker_start + new_body + marker_end

    pattern = re.compile(
        r"<!-- IAI:SECTION:%s START[^>]*-->\n?.*?\n?<!-- IAI:SECTION:%s END -->\n?" % (name, name),
        re.DOTALL,
    )
    if pattern.search(text):
        return pattern.sub(replacement + "\n", text, count=1)
    if text and not text.endswith("\n"):
        text += "\n"
    return text + "\n" + replacement + "\n"


def get_section(text: str, name: str) -> Optional[str]:
    pattern = re.compile(
        r"<!-- IAI:SECTION:%s START[^>]*-->\n?(.*?)\n?<!-- IAI:SECTION:%s END -->" % (name, name),
        re.DOTALL,
    )
    m = pattern.search(text)
    return m.group(1) if m else None


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("%s.tmp-%s" % (path.name, uuid.uuid4().hex[:8]))
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


# ---------------- skeletons ----------------


def industry_skeleton(sector_key: str, sectors: SectorsCfg) -> str:
    sec = sectors.sectors[sector_key]
    lines = ["# %s" % sec.name, "", "> 系统管理的行业长文档：SECTION 标记内由 AI 节级更新；标记外为人工笔记，永不触碰。", ""]
    for section in sec.sections:
        title = INDUSTRY_SECTION_TITLES.get(section, section)
        lines.append("## %s" % title)
        lines.append("<!-- IAI:SECTION:%s START (v1) -->" % section)
        lines.append("（待首次更新）" if section != "changelog" else "| 日期 | 变化 | 证据 |")
        lines.append("<!-- IAI:SECTION:%s END -->" % section)
        lines.append("")
    return "\n".join(lines)


def thesis_skeleton(thesis: Dict) -> str:
    lines = ["# %s" % thesis["title"], ""]
    lines.append("> Thesis 状态: %s · 本文件由 DB 渲染（render --all 可重建）" % THESIS_STATUS_BADGES.get(thesis.get("status", "active"), thesis.get("status")))
    lines.append("")
    bodies = {
        "hypothesis": thesis.get("core_hypothesis", "").strip(),
        "evidence_for": "（暂无支持证据记录）",
        "evidence_against": "（暂无反方证据记录）",
        "falsification": "\n".join(
            "- **%s**：%s（跟踪指标：%s）" % (c.get("id", ""), c.get("condition", ""), c.get("metric", ""))
            for c in thesis.get("falsification_conditions") or []
        ) or "（未定义）",
        "metrics": "\n".join("- %s" % m for m in thesis.get("key_metrics") or []) or "（未定义）",
        "latest_changes": "（暂无变化记录）",
    }
    for section in ("hypothesis", "evidence_for", "evidence_against", "falsification", "metrics", "latest_changes"):
        lines.append("## %s" % THESIS_SECTION_TITLES[section])
        lines.append("<!-- IAI:SECTION:%s START (v1) -->" % section)
        lines.append(bodies[section])
        lines.append("<!-- IAI:SECTION:%s END -->" % section)
        lines.append("")
    return "\n".join(lines)


def ensure_skeletons(vault: Path, sectors: SectorsCfg, theses: List[Dict]) -> List[Path]:
    """Create any missing skeleton files/dirs; never overwrite existing files."""
    created: List[Path] = []
    log = get_logger("renderer")
    for d in ("Industries", "Theses", "Daily", "Weekly"):
        (vault / d).mkdir(parents=True, exist_ok=True)
    for key in sectors.keys():
        path = vault / "Industries" / ("%s.md" % sectors.sectors[key].render_name)
        if not path.exists():
            atomic_write(path, industry_skeleton(key, sectors))
            created.append(path)
    for t in theses:
        path = vault / "Theses" / ("%s.md" % t["id"])
        if not path.exists():
            atomic_write(path, thesis_skeleton(t))
            created.append(path)
    home = vault / "Home.md"
    if not home.exists():
        links = "\n".join(
            "- [[Industries/%s|%s]]" % (sectors.sectors[k].render_name, sectors.sectors[k].name)
            for k in sectors.keys()
        )
        tlinks = "\n".join("- [[Theses/%s|%s]]" % (t["id"], t["title"]) for t in theses)
        atomic_write(home, "# Investment KB\n\n## 行业\n%s\n\n## Thesis\n%s\n" % (links, tlinks))
        created.append(home)
    log.info("skeletons ensured", extra={"ctx": {"created": len(created)}})
    return created


# ---------------- daily report ----------------


def _source_footer(ev: Dict) -> str:
    url_part = "[原文](%s)" % ev["source_url"] if ev.get("source_url") else "无链接"
    return "> 来源: %s · %s · %s · event:%s" % (
        ev.get("source_name", ev.get("source", "?")),
        ev.get("published_at", "?"),
        url_part,
        ev.get("event_id", "?"),
    )


def render_daily_md(model: Dict) -> str:
    """Pure function: report_date, summary(dict), events(list), metrics(dict) -> markdown."""
    lines: List[str] = []
    lines.append("# Daily Research — %s" % model["report_date"])
    lines.append("")
    summary = model.get("summary") or {}
    if summary.get("summary"):
        lines.append("## 综述")
        lines.append("")
        lines.append(summary["summary"])
        lines.append("")
    events = model.get("events") or []
    p0 = [e for e in events if e.get("importance") == "P0"]
    p1 = [e for e in events if e.get("importance") == "P1"]
    for tag, group in (("P0 重大事件", p0), ("P1 重要事件", p1)):
        if not group:
            continue
        lines.append("## %s" % tag)
        lines.append("")
        for ev in group:
            lines.append("### %s" % ev["title"])
            lines.append("")
            meta = " · ".join(
                x for x in [
                    ev.get("importance"),
                    ", ".join(ev.get("sectors") or []),
                    ev.get("event_type"),
                ] if x
            )
            if meta:
                lines.append("*%s*" % meta)
                lines.append("")
            if ev.get("analysis"):
                a = ev["analysis"]
                lines.append("**摘要**：%s" % a.get("summary", ""))
                if a.get("causal_chain"):
                    lines.append("")
                    lines.append("**因果链**：%s" % " → ".join(a["causal_chain"]))
                if a.get("uncertainty"):
                    lines.append("")
                    lines.append("**不确定性**：%s" % "；".join(a["uncertainty"]))
            lines.append("")
            lines.append(_source_footer(ev))
            lines.append("")
    p1_hidden = model.get("p1_hidden") or 0
    if events and p1_hidden:
        lines.append("*注：另有 %d 条 P1 事件未展开（超出日报 P1 展示上限，按时间保留最近条目）。*" % p1_hidden)
        lines.append("")
    if not events:
        lines.append("## 平静日")
        lines.append("")
        lines.append("今日无 P0/P1 事件。市场与行业未见需要更新研究假设的信号。")
        lines.append("")
    watch = (summary or {}).get("tomorrow_watch") or []
    if watch:
        lines.append("## 明日关注")
        lines.append("")
        lines.extend("- %s" % w for w in watch)
        lines.append("")
    metrics = model.get("metrics") or {}
    if metrics:
        lines.append("## 运行指标")
        lines.append("")
        for k in sorted(metrics):
            lines.append("- %s: %s" % (k, metrics[k]))
        lines.append("")
    return "\n".join(lines)
