"""Raw text, region and volume must never reach the database or the logs."""
import logging
from .conftest import csrf_of

SECRET = "zq-secret-widget-4471"


def _dump_db():
    from app.db import SessionLocal, engine
    from sqlalchemy import text
    out = []
    with SessionLocal() as db:
        for (t,) in db.execute(text("select name from sqlite_master where type='table'")):
            for row in db.execute(text(f'select * from "{t}"')):
                out.append(repr(tuple(row)))
    return "\n".join(out)


def test_text_region_volume_not_stored_or_logged(fresh, caplog):
    caplog.set_level(logging.DEBUG)
    c = csrf_of(fresh)
    fresh.post("/assess", data={"material_description": f"cobalt {SECRET}", "sourcing_region": "china", "volume_tier": "large", "csrf": c})
    fresh.post("/api/v1/assess", json={"material_description": f"cobalt {SECRET}", "sourcing_region": "apac", "volume_tier": "small"})
    assert SECRET not in _dump_db()
    assert SECRET not in caplog.text
    assert SECRET not in "\n".join(r.getMessage() for r in caplog.records)


def test_assessment_row_has_no_free_text_columns():
    from app import models as M
    cols = {c.name for c in M.Assessment.__table__.columns}
    assert not cols & {"text", "description", "material_description", "region", "sourcing_region", "volume", "volume_tier", "ip"}


def test_no_ip_columns_anywhere():
    from app import models as M
    for t in M.Base.metadata.tables.values():
        assert not {c.name for c in t.columns} & {"ip", "ip_address", "user_agent"}, t.name
