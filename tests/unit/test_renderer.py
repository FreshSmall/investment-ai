from __future__ import annotations

from pathlib import Path

from app.core.config import load_sectors
from app.knowledge.renderer import (
    anchor,
    atomic_write,
    ensure_skeletons,
    get_section,
    industry_skeleton,
    render_daily_md,
    replace_section,
    thesis_skeleton,
)

SECTORS = load_sectors()


def test_replace_section_preserves_human_content() -> None:
    original = (
        "# 行业文档\n"
        "\n"
        "<!-- IAI:SECTION:overview START (v1) -->\n"
        "旧内容\n"
        "<!-- IAI:SECTION:overview END -->\n"
        "\n"
        "## 我的私人笔记\n"
        "这是人工写的重要洞察，绝不允许被系统改掉。\n"
    )
    updated = replace_section(original, "overview", "AI 新内容", version=2, as_of="2026-09-17")
    assert "AI 新内容" in updated and "旧内容" not in updated
    assert "(v2, 2026-09-17)" in updated
    assert "## 我的私人笔记" in updated
    assert "这是人工写的重要洞察，绝不允许被系统改掉。" in updated  # 字节级保留
    assert get_section(updated, "overview") == "AI 新内容"


def test_replace_section_appends_when_missing() -> None:
    text = "# 只有标题\n"
    out = replace_section(text, "catalysts", "新增节内容")
    assert "新增节内容" in out and get_section(out, "catalysts") == "新增节内容"


def test_daily_render_deterministic_snapshot(tmp_path: Path) -> None:
    model = {
        "report_date": "2026-09-17",
        "summary": {"summary": "算力链催化集中。", "tomorrow_watch": ["跟踪 NVDA 指引"]},
        "events": [
            {
                "event_id": "e4f1a2b3c4d5e6f7",
                "title": "英伟达发布新 GPU",
                "importance": "P0",
                "sectors": ["ai_semiconductor"],
                "event_type": "catalyst",
                "published_at": "2026-09-17 09:32",
                "source_name": "cls",
                "source_url": "https://cls.cn/x",
                "analysis": {
                    "summary": "需求信号强于预期。",
                    "causal_chain": ["算力需求", "服务器", "光模块"],
                    "uncertainty": ["落地节奏未验证"],
                },
            }
        ],
        "metrics": {"events_new": 11, "llm_calls": 27},
    }
    first = render_daily_md(model)
    second = render_daily_md(model)
    assert first == second  # 确定性
    assert "Daily Research — 2026-09-17" in first
    assert "P0 重大事件" in first and "英伟达发布新 GPU" in first
    assert "算力需求 → 服务器 → 光模块" in first
    assert "来源: cls · 2026-09-17 09:32 · [原文](https://cls.cn/x) · event:e4f1a2b3c4d5e6f7" in first
    assert "跟踪 NVDA 指引" in first


def test_daily_render_calm_day() -> None:
    md = render_daily_md({"report_date": "2026-09-18", "summary": {}, "events": [], "metrics": {}})
    assert "平静日" in md and "无 P0/P1" in md


def test_skeleton_three_lifecycle(tmp_path: Path) -> None:
    theses = [{"id": "ai-demand-growth", "title": "AI 需求增长", "core_hypothesis": "假设正文",
               "falsification_conditions": [{"id": "c1", "condition": "条件", "metric": "指标"}],
               "key_metrics": ["CAPEX"], "status": "active"}]
    # 1) 首建
    created = ensure_skeletons(tmp_path, SECTORS, theses)
    assert len(created) == 5  # 3 行业 + 1 thesis + Home
    ind = tmp_path / "Industries" / "AI-Semiconductor.md"
    assert ind.exists()
    assert get_section(ind.read_text(encoding="utf-8"), "overview") is not None

    # 2) 更新（人工加笔记后节级替换，笔记保留）
    text = ind.read_text(encoding="utf-8") + "\n## 人工补充\n保持不动\n"
    atomic_write(ind, replace_section(text, "overview", "首次 AI 更新内容", 2, "2026-09-17"))
    updated = ind.read_text(encoding="utf-8")
    assert "首次 AI 更新内容" in updated and "保持不动" in updated

    # 3) 重建路径：ensure 不覆盖已存在文件
    again = ensure_skeletons(tmp_path, SECTORS, theses)
    assert again == []
    assert "首次 AI 更新内容" in ind.read_text(encoding="utf-8")


def test_thesis_skeleton_contains_falsification() -> None:
    t = {"id": "x", "title": "T", "core_hypothesis": "H", "status": "active",
         "falsification_conditions": [{"id": "c1", "condition": "CAPEX 下滑", "metric": "CAPEX"}],
         "key_metrics": ["M1"]}
    md = thesis_skeleton(t)
    assert "CAPEX 下滑" in md and "证伪条件" in md
    assert "🟢 active" in md  # 状态徽章而非评分


def test_industry_skeleton_all_sections() -> None:
    md = industry_skeleton("power_energy", SECTORS)
    for section in SECTORS.sectors["power_energy"].sections:
        assert "IAI:SECTION:%s START" % section in md


def test_anchor_deterministic() -> None:
    assert anchor("e4f1a2b3c4d5e6f7") == "ee4f1"
    assert anchor("e4f1a2b3c4d5e6f7") == anchor("e4f1a2b3c4d5e6f7")
