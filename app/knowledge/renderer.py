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


# ---------------- thesis long file (V0.2) ----------------

_STATUS_LINE_RE = re.compile(r"^> Thesis 状态: .*$", re.MULTILINE)


def _evidence_line(ev: Dict) -> str:
    badge = DIRECTION_BADGES.get(ev.get("direction", "neutral"), ev.get("direction", "?"))
    weight = "强" if ev.get("weight") == "strong" else "弱"
    note = (ev.get("note") or "").replace("\n", " ").strip()
    link = "[[Daily/%s#%s|%s]]" % (ev.get("review_date"), anchor(ev.get("event_id", "")), ev.get("review_date"))
    return "- %s（%s）%s — %s" % (badge, weight, note, link)


def write_thesis_file(vault: Path, thesis: Dict, evidence_rows: List[Dict]) -> Path:
    """Update one Thesis long file from DB truth (arch §9).

    Rewrites ONLY section bodies + the status line; human notes outside
    sections are preserved byte-for-byte. Evidence list keeps the newest
    20; latest_changes keeps the newest 10 (rolling window, DB retains all).
    """
    path = vault / "Theses" / ("%s.md" % thesis["id"])
    text = path.read_text(encoding="utf-8") if path.exists() else thesis_skeleton(thesis)

    badge = THESIS_STATUS_BADGES.get(thesis.get("status", "active"), thesis.get("status"))
    status_line = "> Thesis 状态: %s · 本文件由 DB 渲染（render --all 可重建）" % badge
    if _STATUS_LINE_RE.search(text):
        text = _STATUS_LINE_RE.sub(status_line, text, count=1)
    else:
        text = text.replace("# %s\n" % thesis["title"], "# %s\n\n%s\n" % (thesis["title"], status_line), 1)

    text = replace_section(
        text, "hypothesis", (thesis.get("core_hypothesis") or "").strip(),
        as_of=str(thesis.get("version", 1)),
    )
    text = replace_section(
        text, "falsification",
        "\n".join(
            "- **%s**：%s（跟踪指标：%s）" % (c.get("id", ""), c.get("condition", ""), c.get("metric", ""))
            for c in thesis.get("falsification_conditions") or []
        ) or "（未定义）",
    )
    text = replace_section(
        text, "metrics",
        "\n".join("- %s" % m for m in thesis.get("key_metrics") or []) or "（未定义）",
    )

    recent = evidence_rows[:20]
    for section, direction in (("evidence_for", "supporting"), ("evidence_against", "contradicting")):
        rows = [e for e in recent if e.get("direction") == direction]
        text = replace_section(
            text, section,
            "\n".join(_evidence_line(e) for e in rows) or "（暂无证据记录）",
        )
    changes = evidence_rows[:10]
    text = replace_section(
        text, "latest_changes",
        "\n".join(
            "- %s %s" % (e.get("review_date"), DIRECTION_BADGES.get(e.get("direction", "neutral"), ""))
            + ("：{}".format((e.get("note") or "").replace("\n", " ").strip()[:80]) if e.get("note") else "")
            for e in changes
        ) or "（暂无变化记录）",
    )

    atomic_write(path, text)
    return path


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
    # V0.3: market review board
    market = model.get("market") or {}
    review = market.get("review") or {}
    if market.get("indices") or review:
        lines.append("## 市场复盘")
        lines.append("")
        if market.get("indices"):
            idx_line = " · ".join(
                "%s %s%%（%s 亿）" % (i.get("name", "?"), i.get("change_pct", 0), i.get("amount_yi", 0))
                for i in market["indices"]
            )
            lines.append("*指数*：%s" % idx_line)
            lines.append("")
        if market.get("sectors_top"):
            top_line = "、".join("%s %s%%" % (s.get("name", "?"), s.get("change_pct", 0)) for s in market["sectors_top"][:3])
            lines.append("*领涨*：%s" % top_line)
            lines.append("")
        if review.get("market_summary"):
            lines.append(review["market_summary"])
            lines.append("")
        if review.get("style_note"):
            lines.append("**风格**：%s" % review["style_note"])
            lines.append("")
        if review.get("risk_flags"):
            lines.append("**风险信号**：%s" % "；".join(review["risk_flags"]))
            lines.append("")
    # V0.2: thesis review board
    thesis_updates = model.get("thesis_updates") or []
    if thesis_updates:
        lines.append("## Thesis 复盘")
        lines.append("")
        for t in thesis_updates:
            badge = DIRECTION_BADGES.get(t.get("direction"), t.get("direction", "?"))
            status_note = "（状态变更 → %s）" % t["new_status"] if t.get("status_changed") else ""
            lines.append("- **%s**：%s%s — %s [[Theses/%s|→]]" % (
                t.get("title", t.get("thesis_id")), badge, status_note,
                (t.get("note") or "").replace("\n", " ")[:120], t.get("thesis_id"),
            ))
        lines.append("")
    company_impacts = model.get("company_impacts") or []
    if company_impacts:
        lines.append("## 自选股影响")
        lines.append("")
        for c in company_impacts:
            companies = "、".join(x.get("name", "?") for x in c.get("companies", [])[:4]) or "—"
            lines.append("- **%s**（%s）：%s" % (
                companies, c.get("importance", ""),
                (c.get("summary") or "").replace("\n", " ")[:140],
            ))
        lines.append("")
    watch = (summary or {}).get("tomorrow_watch") or []
    if watch:
        lines.append("## 明日关注")
        lines.append("")
        lines.extend("- %s" % w for w in watch)
        lines.append("")
    metrics = model.get("metrics") or {}
    # 稳定指标白名单：token 类字段随 refresh 重跑原地更新（行业现文反馈循环），
    # 渲染它们会破坏日报字节级确定性；token 明细在 runs.stats_json 可查
    stable_metrics = {k: v for k, v in metrics.items() if k in (
        "events_new_today", "by_importance", "analyses_today", "estimated_cost_cny",
    )}
    if stable_metrics:
        lines.append("## 运行指标")
        lines.append("")
        for k in sorted(stable_metrics):
            lines.append("- %s: %s" % (k, stable_metrics[k]))
        lines.append("")
    return "\n".join(lines)
