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
