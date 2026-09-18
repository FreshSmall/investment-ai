from __future__ import annotations

from pathlib import Path

from app.core.config import load_sectors
from app.knowledge.renderer import (
    anchor,
    atomic_write,
    ensure_skeletons,
    get_section,
    industry_skeleton,
    normalize_section_spacing,
    render_daily_md,
    replace_section,
    thesis_skeleton,
    write_thesis_file,
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


def test_replace_section_blank_line_around_body() -> None:
    # marker 与正文之间必须空行：紧贴 HTML 注释的表格/列表在 Obsidian 中不渲染
    updated = replace_section("# T\n", "changelog", "| 日期 | 变化 |\n|---|---|\n| 2026-09-18 | x |")
    assert "<!-- IAI:SECTION:changelog START (v1) -->\n\n| 日期 | 变化 |" in updated
    assert "| 2026-09-18 | x |\n\n<!-- IAI:SECTION:changelog END -->" in updated
    assert updated == replace_section(updated, "changelog", "| 日期 | 变化 |\n|---|---|\n| 2026-09-18 | x |")  # 幂等
    # 存量迁移：旧格式（无空行）规范化后与新写入一致
    legacy = "# T\n<!-- IAI:SECTION:overview START (v1) -->\n旧正文\n<!-- IAI:SECTION:overview END -->\n"
    assert normalize_section_spacing(legacy) == (
        "# T\n<!-- IAI:SECTION:overview START (v1) -->\n\n旧正文\n\n<!-- IAI:SECTION:overview END -->\n"
    )


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
    # 因果链竖排：首行起点，后续 → 前缀（长链不再挤成单段）
    assert "**因果链**" in first
    assert "- 算力需求\n- → 服务器\n- → 光模块" in first
    # 不确定性逐条列点，不再用；拼接
    assert "**不确定性**\n\n- 落地节奏未验证" in first
    assert "来源: cls · 2026-09-17 09:32 · [原文](https://cls.cn/x) · event:e4f1a2b3c4d5e6f7 ^ee4f1" in first
    assert "跟踪 NVDA 指引" in first


def test_daily_render_metrics_formatted() -> None:
    model = {
        "report_date": "2026-09-18",
        "summary": {},
        "events": [],
        "metrics": {
            "events_new_today": 62,
            "by_importance": {"P2": 20, "P0": 5, "P1": 17},
            "analyses_today": 13,
            "estimated_cost_cny": 0.6063999999999999,
            "llm_calls": 27,  # 不稳定字段：白名单外不渲染
        },
    }
    md = render_daily_md(model)
    assert "- 新增事件: 62" in md
    assert "- 重要性分布: P0 5 · P1 17 · P2 20" in md  # dict repr 不进正文
    assert "- 当日分析: 13" in md
    assert "- 预估成本: ¥0.61" in md  # 浮点尾数噪声不进正文
    assert "llm_calls" not in md and "{" not in md


def test_daily_render_market_indices_table() -> None:
    model = {
        "report_date": "2026-09-18",
        "summary": {},
        "events": [],
        "market": {
            "indices": [
                {"name": "上证指数", "change_pct": 0.51, "amount_yi": 2847.5},
                {"name": "创业板指", "change_pct": 1.02, "amount_yi": 1502.1},
            ],
            "sectors_top": [{"name": "超市", "change_pct": 3.74}],
        },
        "metrics": {},
    }
    md = render_daily_md(model)
    assert "| 指数 | 涨跌幅 | 成交额(亿) |" in md
    assert "|---|---|---|" in md
    assert "| 上证指数 | +0.51% | 2847.5 |" in md
    assert "| 创业板指 | +1.02% | 1502.1 |" in md
    assert "*领涨*：超市 +3.74%" in md


def test_daily_render_calm_day() -> None:
    md = render_daily_md({"report_date": "2026-09-18", "summary": {}, "events": [], "metrics": {}})
    assert "平静日" in md and "无 P0/P1" in md


def test_daily_render_p1_truncation_note() -> None:
    model = {
        "report_date": "2026-09-17",
        "summary": {},
        "events": [
            {"event_id": "a" * 16, "title": "P1事件一", "importance": "P1", "sectors": [],
             "event_type": "catalyst", "published_at": "2026-09-17 10:00",
             "source_name": "cls", "source_url": None, "analysis": None},
        ],
        "metrics": {},
        "p1_hidden": 53,
    }
    md = render_daily_md(model)
    assert "另有 53 条 P1 事件未展开" in md
    # 无截断时不出现提示
    md2 = render_daily_md({**model, "p1_hidden": 0})
    assert "未展开" not in md2


def test_daily_render_overflow_anchor_index() -> None:
    model = {
        "report_date": "2026-09-17",
        "summary": {},
        "events": [],
        "metrics": {},
        "p1_hidden": 1,
        "p1_overflow": [
            {"event_id": "e1726f0d1e2a3b4c", "title": "被裁掉的P1事件标题", "importance": "P1"},
        ],
    }
    md = render_daily_md(model)
    assert "## 未展开事件索引" in md
    assert "- 被裁掉的P1事件标题 · event:e1726f0d1e2a3b4c ^ee172" in md  # 锚点索引提供回链落点


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
    assert "| 日期 | 变化 | 证据 |\n|---|---|---|" in md  # changelog 表带分隔行


def test_write_thesis_file_evidence_table(tmp_path: Path) -> None:
    thesis = {"id": "t1", "title": "T1", "core_hypothesis": "H", "status": "weakened",
              "falsification_conditions": [], "key_metrics": [], "version": 2}
    long_note = "长" * 100
    evidence = [
        {"review_date": "2026-09-18", "direction": "supporting", "weight": "strong",
         "note": "华为发布昇腾960超节点", "event_id": "e17c8a5381c14a599"},
        {"review_date": "2026-09-18", "direction": "contradicting", "weight": "weak",
         "note": "含竖线|的备注", "event_id": "e0930abcdef12345"},
        {"review_date": "2026-09-17", "direction": "supporting", "weight": "weak",
         "note": long_note, "event_id": "eabcdef123456789"},
    ]
    path = write_thesis_file(tmp_path, thesis, evidence)
    text = path.read_text(encoding="utf-8")

    # 证据区为表格：表头 + 分隔行 + 列对齐行
    assert "| 日期 | 方向 | 强弱 | 证据 | 来源 |" in text
    assert "|---|---|---|---|---|" in text
    assert "| 2026-09-18 | 🟢 支持 | 强 | 华为发布昇腾960超节点 | [↗](../Daily/2026-09-18.md#^ee17c) |" in text
    assert "含竖线／的备注" in text  # note 内竖线替换，不破坏表格结构
    assert "🟡 weakened" in text     # 状态行随 DB 重写

    # latest_changes 滚动窗截断补省略号（不再无声切半句）
    changes = get_section(text, "latest_changes")
    assert "…" in changes and long_note not in changes


def test_anchor_deterministic() -> None:
    assert anchor("e4f1a2b3c4d5e6f7") == "ee4f1"
    assert anchor("e4f1a2b3c4d5e6f7") == anchor("e4f1a2b3c4d5e6f7")
