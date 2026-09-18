"""Updater 单测：SectionDiff 应用/changelog 滚动窗/人工内容保护。"""

from __future__ import annotations

from pathlib import Path

from app.core.config import load_sectors
from app.knowledge.renderer import industry_skeleton, atomic_write
from app.knowledge.updater import apply_industry_update, build_section_ctx, industry_path

EID = "addf091f74bca86a"


def _vault(tmp_path: Path) -> Path:
    sectors = load_sectors()
    key = sectors.keys()[0]
    path = industry_path(tmp_path, key, sectors)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, industry_skeleton(key, sectors))
    return tmp_path


def test_apply_update_rewrites_only_changed_sections(tmp_path) -> None:
    sectors = load_sectors()
    key = sectors.keys()[0]
    vault = _vault(tmp_path)
    path = industry_path(vault, key, sectors)

    # 人工内容预置（必须字节级保留）
    human = "\n## 我的行业笔记\n这是人工写的。\n"
    atomic_write(path, path.read_text(encoding="utf-8") + human)

    update = {
        "sections": [
            {"name": "overview", "content": "AI 需求驱动景气上行。", "changed": True, "based_on_event_ids": [EID]},
            {"name": "catalysts", "content": "被忽略的假内容", "changed": False},  # 未变化节内容必须被丢弃
        ],
        "changelog_rows": [{"change": "景气上行", "evidence_event_id": EID}],
    }
    applied = apply_industry_update(vault, key, sectors, update, "2026-09-17")
    assert applied == {"sections_changed": 1, "changelog_added": 1}

    text = path.read_text(encoding="utf-8")
    assert "AI 需求驱动景气上行。" in text
    assert "被忽略的假内容" not in text          # changed=false 的内容不落地
    assert "（待首次更新）" in text               # 其余节保持骨架占位
    assert human in text                          # 人工内容字节级保留
    assert "| 日期 | 变化 | 证据 |\n|---|---|---|" in text  # 表头必须带分隔行（Obsidian 渲染要求）
    # 表格内链接为 markdown 形式（无竖线，Obsidian 表格编辑器重排不会破坏）+ 块引用锚点
    assert "| 2026-09-17 | 景气上行 | [2026-09-17](../Daily/2026-09-17.md#^eaddf) |" in text


def test_changelog_rolling_window_and_prepend(tmp_path) -> None:
    sectors = load_sectors()
    key = sectors.keys()[0]
    vault = _vault(tmp_path)

    for day in range(1, 33):  # 32 天的变化，窗口只保留最近 30
        apply_industry_update(vault, key, sectors, {
            "sections": [],
            "changelog_rows": [{"change": "变化 %02d" % day, "evidence_event_id": EID}],
        }, "2026-09-%02d" % day)

    text = industry_path(vault, key, sectors).read_text(encoding="utf-8")
    rows = [ln for ln in text.splitlines() if ln.startswith("| 2026-")]
    assert len(rows) == 30
    assert "变化 32" in rows[0] and "变化 31" in rows[1]  # 新行在前（倒序）
    assert "变化 02" not in text and "变化 01" not in text  # 最旧两行被滚出（零填充避免子串误判）


def test_no_change_no_write(tmp_path) -> None:
    sectors = load_sectors()
    key = sectors.keys()[0]
    vault = _vault(tmp_path)
    path = industry_path(vault, key, sectors)
    before = path.read_text(encoding="utf-8")

    applied = apply_industry_update(vault, key, sectors, {
        "sections": [{"name": "overview", "content": "x", "changed": False}],
        "changelog_rows": [],
    }, "2026-09-17")
    assert applied == {"sections_changed": 0, "changelog_added": 0}
    assert path.read_text(encoding="utf-8") == before  # 无变化不写文件


def test_build_section_ctx_reads_current_bodies(tmp_path) -> None:
    sectors = load_sectors()
    key = sectors.keys()[0]
    vault = _vault(tmp_path)
    ctx = build_section_ctx(vault, key, sectors)
    assert [s["name"] for s in ctx] == ["overview", "supply_demand", "catalysts", "risks", "metrics"]
    assert all(s["content"] == "（待首次更新）" for s in ctx)
