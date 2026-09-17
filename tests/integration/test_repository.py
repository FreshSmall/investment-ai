from __future__ import annotations

import json
from datetime import date, datetime

from app.db.repository import Repository
from app.domain.event import EventStatus, NormalizedEvent
from app.domain.report import RunStatus


def make_ev(source: str, source_id: str, title: str = None, content: str = None, published=None) -> NormalizedEvent:
    title = title if title is not None else "标题-%s-%s" % (source, source_id)
    content = content if content is not None else "正文-%s-%s" % (source, source_id)
    return NormalizedEvent(
        source=source,
        source_id=source_id,
        title=title,
        content=content,
        url=None,
        published_at=published or datetime(2026, 9, 17, 10, 0),
        collected_at=datetime(2026, 9, 17, 20, 0),
        raw={},
        norm_title=title,
        norm_content=content,
    )


def test_upsert_events_idempotent(db_session) -> None:
    repo = Repository(db_session)
    batch = [make_ev("cls", "1"), make_ev("cls", "2"), make_ev("eastmoney", "9")]

    first = repo.upsert_events(batch)
    assert (first.inserted, first.dup_source, first.dup_hash) == (3, 0, 0)

    second = repo.upsert_events(batch)
    assert (second.inserted, second.dup_source, second.dup_hash) == (0, 3, 0)


def test_upsert_events_cross_source_hash_dedup(db_session) -> None:
    repo = Repository(db_session)
    repo.upsert_events([make_ev("cls", "1", title="同一标题", content="同一正文")])
    stats = repo.upsert_events(
        [make_ev("eastmoney", "77", title="同一标题", content="同一正文")]
    )
    # source_id 新但 content_hash 相同 -> dup_hash，不落库
    assert (stats.inserted, stats.dup_hash) == (0, 1)


def test_classify_state_machine(db_session) -> None:
    repo = Repository(db_session)
    ev = make_ev("cls", "1")
    repo.upsert_events([ev])
    repo.mark_classified(ev.event_id, ["ai_semiconductor"], "catalyst", "P0")
    row = repo.get_event(ev.event_id)
    assert row.status == EventStatus.CLASSIFIED.value
    assert json.loads(row.sectors) == ["ai_semiconductor"]

    pending = repo.get_events_for_analysis()
    assert [r.id for r in pending] == [ev.event_id]

    repo.mark_event_status(ev.event_id, EventStatus.ANALYZED)
    assert repo.get_event(ev.event_id).status == EventStatus.ANALYZED
    assert repo.get_events_for_analysis() == []


def test_mark_classified_p3_archives(db_session) -> None:
    repo = Repository(db_session)
    ev = make_ev("cls", "1")
    repo.upsert_events([ev])
    repo.mark_classified(ev.event_id, [], "other", "P3")
    assert repo.get_event(ev.event_id).status == EventStatus.ARCHIVED.value


def test_unclassified_retried_next_round(db_session) -> None:
    repo = Repository(db_session)
    ev = make_ev("cls", "1")
    repo.upsert_events([ev])
    repo.mark_event_status(ev.event_id, EventStatus.UNCLASSIFIED)
    assert [r.id for r in repo.get_events_for_classify()] == [ev.event_id]


def test_save_analysis_unique_semantics(db_session) -> None:
    repo = Repository(db_session)
    id1, created1 = repo.save_analysis(
        "event_analysis", "m", "v1", {"summary": "x"}, event_id="abc", input_tokens=10, output_tokens=5
    )
    id2, created2 = repo.save_analysis(
        "event_analysis", "m", "v1", {"summary": "y"}, event_id="abc"
    )
    assert created1 and not created2 and id1 == id2

    # 不同 prompt_version 是新分析（质量回归对比的基础）
    id3, created3 = repo.save_analysis("event_analysis", "m", "v2", {"summary": "z"}, event_id="abc")
    assert created3 and id3 != id1

    # 聚合类：report_date 唯一
    _, ca = repo.save_analysis("daily_summary", "m", "v1", {}, report_date=date(2026, 9, 17))
    _, cb = repo.save_analysis("daily_summary", "m", "v1", {}, report_date=date(2026, 9, 17))
    assert ca and not cb


def test_run_lifecycle(db_session) -> None:
    repo = Repository(db_session)
    repo.create_run("r1", "daily", date(2026, 9, 17), datetime(2026, 9, 17, 20, 0))
    assert repo.latest_run(date(2026, 9, 17)).status == RunStatus.RUNNING.value
    repo.finish_run(
        "r1", RunStatus.SUCCESS, datetime(2026, 9, 17, 20, 5), {"events_new": 3}
    )
    latest = repo.latest_run(date(2026, 9, 17))
    assert latest.status == RunStatus.SUCCESS.value and latest.stats_json["events_new"] == 3


def test_report_upsert_idempotent(db_session) -> None:
    repo = Repository(db_session)
    repo.upsert_report("daily", date(2026, 9, 17), "/vault/Daily/x.md", {"a": 1})
    repo.upsert_report("daily", date(2026, 9, 17), "/vault/Daily/x.md", {"a": 2})
    rows = db_session.query(__import__("app.db.models", fromlist=["ReportRow"]).ReportRow).all()
    assert len(rows) == 1 and rows[0].metrics_json["a"] == 2


def test_get_report_events_window(db_session) -> None:
    repo = Repository(db_session)
    e_old = make_ev("cls", "1", published=datetime(2026, 9, 15, 8, 0))    # 窗口外
    e_edge = make_ev("cls", "2", published=datetime(2026, 9, 16, 13, 0))   # 昨日12:00后（窗口内）
    e_new = make_ev("cls", "3", published=datetime(2026, 9, 17, 9, 0))
    repo.upsert_events([e_old, e_edge, e_new])
    for ev in (e_old, e_edge, e_new):
        repo.mark_classified(ev.event_id, ["ai_semiconductor"], "catalyst", "P0")
        repo.mark_event_status(ev.event_id, EventStatus.ANALYZED)
    got = repo.get_report_events(date(2026, 9, 17))
    assert {r.source_id for r in got} == {"2", "3"}


# ---------------- V0.2: companies / thesis evidence / status machine ----------------

def _seed_thesis(session, thesis_id: str = "ai-demand-growth", status: str = "active"):
    from app.db.models import ThesisRow

    row = ThesisRow(
        id=thesis_id, title="AI 需求增长", core_hypothesis="假设正文",
        falsification_conditions=[{"id": "c1", "condition": "CAPEX 连续两季下降", "metric": "CAPEX"}],
        key_metrics=["云厂商 CAPEX"], related_sectors=["ai_semiconductor"], status=status,
    )
    session.add(row)
    session.commit()
    return row


def _evidence(event_id: str, direction: str, weight: str = "strong") -> dict:
    return {"event_id": event_id, "direction": direction, "weight": weight, "note": "证据说明"}


def test_seed_companies_idempotent(db_session) -> None:
    repo = Repository(db_session)
    companies = [
        {"code": "300308", "name": "中际旭创", "sector": "ai_semiconductor", "watched": True, "profile": "光模块龙头"},
        {"code": "688017", "name": "绿的谐波", "sector": "robotics", "watched": True, "profile": "谐波减速器"},
    ]
    assert repo.seed_companies(companies) == 2
    assert repo.seed_companies(companies) == 2  # upsert，不报错
    rows = repo.list_companies()
    assert {r.code for r in rows} == {"300308", "688017"}
    assert rows[0].profile == {"text": "光模块龙头"}


def test_thesis_evidence_upsert_no_duplicate_rows(db_session) -> None:
    from app.db.models import EventRow

    repo = Repository(db_session)
    repo.upsert_events([make_ev("cls", "e1", title="订单", content="正文")])
    ev = db_session.query(EventRow).first()

    items = [_evidence(ev.id, "supporting")]
    assert repo.save_thesis_evidence("t1", date(2026, 9, 17), items) == 1
    # 重跑同日同证据：行数不变（联合主键 upsert，幂等由行数保证）
    repo.save_thesis_evidence("t1", date(2026, 9, 17), items)
    assert len(repo.list_thesis_evidence("t1")) == 1


def test_apply_review_single_day_contradicting_keeps_active(db_session) -> None:
    from app.db.models import EventRow

    repo = Repository(db_session)
    _seed_thesis(db_session)
    repo.upsert_events([make_ev("cls", "e1"), make_ev("cls", "e2")])
    ids = [r.id for r in db_session.query(EventRow).all()]

    result = repo.apply_thesis_review(
        "ai-demand-growth", date(2026, 9, 17), "contradicting",
        [_evidence(ids[0], "contradicting"), _evidence(ids[1], "contradicting")],
    )
    assert result["status_changed"] is False  # 单日强反证不动状态（防噪音翻转）
    assert repo.get_thesis("ai-demand-growth").status == "active"


def test_apply_review_streak_weakened_after_three_days(db_session) -> None:
    from app.db.models import EventRow

    repo = Repository(db_session)
    _seed_thesis(db_session)
    repo.upsert_events([make_ev("cls", "e%d" % i) for i in range(1, 4)])
    ids = [r.id for r in db_session.query(EventRow).all()]

    for d, ev_id in zip((date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 17)), ids):
        repo.apply_thesis_review(
            "ai-demand-growth", d, "contradicting", [_evidence(ev_id, "contradicting", "strong")]
        )
    t = repo.get_thesis("ai-demand-growth")
    assert t.status == "weakened"
    assert t.version == 2  # 流转记录进 thesis_versions


def test_apply_review_falsification_triggered(db_session) -> None:
    from app.db.models import EventRow

    repo = Repository(db_session)
    _seed_thesis(db_session)
    repo.upsert_events([make_ev("cls", "e1")])
    ev_id = db_session.query(EventRow).first().id

    result = repo.apply_thesis_review(
        "ai-demand-growth", date(2026, 9, 17), "contradicting",
        [_evidence(ev_id, "contradicting")], falsification_triggered=True,
    )
    assert result["status_changed"] and result["new_status"] == "falsified"
    assert repo.consecutive_contradicting_days("ai-demand-growth", date(2026, 9, 17)) == 1


def test_weak_counter_evidence_never_flips_day_direction(db_session) -> None:
    """Devil Advocate 上限 weak：weak 反证不应把日方向判为 contradicting（arch §7.4）。"""
    from app.db.models import EventRow

    repo = Repository(db_session)
    repo.upsert_events([make_ev("cls", "s1"), make_ev("cls", "c1")])
    ids = [r.id for r in db_session.query(EventRow).all()]
    repo.save_thesis_evidence("t1", date(2026, 9, 17), [
        _evidence(ids[0], "supporting", "strong"),
        _evidence(ids[1], "contradicting", "weak"),
    ])
    assert repo.day_direction("t1", date(2026, 9, 17)) == "supporting"


def test_analyses_for_date_scopes_by_thesis(db_session) -> None:
    repo = Repository(db_session)
    repo.save_analysis(strategy="thesis_review", model="m", prompt_version="v1",
                       result={"direction": "neutral"}, report_date=date(2026, 9, 17), thesis_id="a")
    repo.save_analysis(strategy="thesis_review", model="m", prompt_version="v1",
                       result={"direction": "supporting"}, report_date=date(2026, 9, 17), thesis_id="b", refresh=True)
    rows = repo.analyses_for_date(date(2026, 9, 17), "thesis_review")
    assert len(rows) == 2  # 同日多 thesis 不互相覆盖（uk_agg 含 thesis_id）
    assert {r.thesis_id for r in rows} == {"a", "b"}
