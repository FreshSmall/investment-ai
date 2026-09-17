"""V0.4 集成测试：公告采集 → L0 bypass → 入库 → 幂等。"""

from __future__ import annotations

from app.db.repository import Repository
from app.db.seed import seed_companies


def test_announcements_l0_bypass_and_idempotent(pipeline_ctx) -> None:
    from app.pipeline.steps.announcements import AnnouncementStep
    from app.pipeline.steps.normalize import IngestStep

    ctx = pipeline_ctx
    seed_companies(ctx.repo._s)
    # 公告源样本 3 条（watched 交集），新闻 mock 12 条
    ctx.shared["raw_events"] = []

    res = AnnouncementStep().run(ctx)
    assert res.ok and res.stats["announcements"] == 3
    assert len(ctx.shared["raw_events"]) == 3

    ing = IngestStep().run(ctx)
    assert ing.ok
    # l0_bypass：含"输变电"这类非行业关键词标题的官方公告也必须入库
    from app.db.models import EventRow

    rows = ctx.repo._s.query(EventRow).filter(EventRow.source == "cninfo").all()
    assert len(rows) == 3
    assert any("特变电工" in r.title for r in rows)

    # 幂等：重跑公告步骤 + 入库 → 零新增（uk_source）
    AnnouncementStep().run(ctx)
    ing2 = IngestStep().run(ctx)
    assert ing2.stats["events_new"] == 0


def test_announcement_step_degrades_without_provider(pipeline_ctx) -> None:
    from app.pipeline.steps.announcements import AnnouncementStep

    ctx = pipeline_ctx
    ctx.announcement_provider = None
    res = AnnouncementStep().run(ctx)
    assert res.ok and res.stats.get("skipped") == "no provider"


def test_announcement_step_error_degrades(pipeline_ctx) -> None:
    from app.pipeline.steps.announcements import AnnouncementStep
    from app.db.seed import seed_companies

    ctx = pipeline_ctx
    seed_companies(ctx.repo._s)

    class Broken:
        name = "broken"

        def fetch_for_codes(self, codes, since, limit_per_code=15):
            raise RuntimeError("upstream down")

    ctx.announcement_provider = Broken()
    res = AnnouncementStep().run(ctx)
    assert res.ok and "announcement_error" in res.stats
