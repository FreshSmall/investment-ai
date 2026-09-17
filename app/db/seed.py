"""Idempotent seeding from config YAML (first-run bootstrap): theses + companies."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from sqlalchemy.orm import Session

from app.core.config import CONFIG_DIR
from app.core.log import get_logger
from app.db.models import ThesisRow, ThesisVersionRow


def seed_theses(session: Session, path: Optional[Path] = None) -> int:
    """Insert theses that do not exist yet. Returns number of inserted rows."""
    path = path or (CONFIG_DIR / "theses.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    log = get_logger("seed")
    inserted = 0
    for item in data.get("theses", []):
        thesis_id = item["id"]
        if session.get(ThesisRow, thesis_id) is not None:
            continue
        row = ThesisRow(
            id=thesis_id,
            title=item["title"],
            core_hypothesis=item["core_hypothesis"].strip(),
            falsification_conditions=item.get("falsification_conditions", []),
            key_metrics=item.get("key_metrics"),
            related_companies=item.get("related_companies"),
            related_sectors=item.get("related_sectors"),
            status="active",
        )
        session.add(row)
        session.add(
            ThesisVersionRow(
                thesis_id=thesis_id,
                version=1,
                snapshot={"title": row.title, "core_hypothesis": row.core_hypothesis, "status": "active"},
                changed_by="human",
            )
        )
        inserted += 1
        log.info("seed thesis", extra={"ctx": {"id": thesis_id}})
    session.commit()
    return inserted


def seed_companies(session: Session, path: Optional[Path] = None) -> int:
    """Upsert companies from config/companies.yaml (V0.2). Returns row count."""
    from app.db.repository import Repository

    path = path or (CONFIG_DIR / "companies.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    companies = data.get("companies", [])
    count = Repository(session).seed_companies(companies)
    get_logger("seed").info("seed companies", extra={"ctx": {"rows": count}})
    return count


if __name__ == "__main__":
    from app.db.engine import get_session_factory

    with get_session_factory()() as s:
        count = seed_theses(s)
        print("seeded %d theses" % count)
        print("seeded %d companies" % seed_companies(s))
