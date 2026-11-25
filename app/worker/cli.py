"""Scheduled jobs:  python -m app.worker.cli <publish|monitor|reverify|housekeeping|daily>"""
import sys
import logging
from ..db import engine, Base, SessionLocal
from .. import models  # noqa: F401
from ..logging_setup import setup
from ..services import snapshots as S, sessions
from . import monitor


def main(argv):
    setup()
    log = logging.getLogger("mse.cli")
    job = argv[1] if len(argv) > 1 else "daily"
    if engine.url.get_backend_name() == "sqlite":
        Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        S.ensure_materials(db)
        steps = {"daily": ["publish", "monitor", "reverify", "housekeeping"]}.get(job, [job])
        for step in steps:
            try:
                if step == "publish":
                    with monitor.job(db, "publish") as jr:
                        r = S.publish_all(db)
                        jr.detail = {"created": len(r["created"]), "unchanged": len(r["unchanged"])}
                elif step == "monitor":
                    monitor.run_monitor(db)
                elif step == "reverify":
                    with monitor.job(db, "reverify") as jr:
                        jr.detail = monitor.reverify(db)
                elif step == "housekeeping":
                    with monitor.job(db, "housekeeping") as jr:
                        jr.detail = {"sessions_purged": sessions.purge_expired(db)}
                else:
                    log.error("unknown job %s", step)
                    return 2
                log.info("job %s ok", step)
            except Exception:
                log.exception("job %s failed", step)     # a failed job keeps the last good scores and shows as stale
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
