import pytest
from sqlalchemy import select, text
from app.db import SessionLocal
from app import models as M
from app.services import snapshots as S, chain
from app.engine import taxonomy


def test_log_is_intact_after_publish(client):
    r = client.get("/api/v1/log/verify").json()
    assert r["intact"] and r["entries"] >= 19 and r["first_break_snapshot_id"] is None


def test_entries_link_to_each_other(client):
    with SessionLocal() as db:
        rows = db.execute(select(M.ScoreSnapshot).where(M.ScoreSnapshot.digest.is_not(None)).order_by(M.ScoreSnapshot.id)).scalars().all()
        assert rows[0].prev_digest == chain.GENESIS
        for a, b in zip(rows, rows[1:]):
            assert b.prev_digest == a.digest


def test_tampering_is_detected_and_located(client):
    with SessionLocal() as db:
        sn = db.execute(select(M.ScoreSnapshot).where(M.ScoreSnapshot.material_id == "tin")
                        .where(M.ScoreSnapshot.digest.is_not(None)).order_by(M.ScoreSnapshot.id)).scalars().first()
        sid, old = sn.id, sn.composite
        db.execute(text("update score_snapshot set composite = :c where id = :i"), {"c": old + 5, "i": sid})
        db.commit()
        try:
            v = S.verify_chain(db)
            assert not v["intact"] and v["first_break_snapshot_id"] == sid
            assert client.get(f"/api/v1/snapshots/{sid}/verify").json()["reproduced"] is False
        finally:
            db.execute(text("update score_snapshot set composite = :c where id = :i"), {"c": old, "i": sid})
            db.commit()
        assert S.verify_chain(db)["intact"]


def test_deleted_entry_breaks_the_chain(client):
    with SessionLocal() as db:
        rows = db.execute(select(M.ScoreSnapshot).where(M.ScoreSnapshot.digest.is_not(None)).order_by(M.ScoreSnapshot.id)).scalars().all()
        victim = rows[3]
        row = {c.name: getattr(victim, c.name) for c in M.ScoreSnapshot.__table__.columns}
        db.execute(text("delete from score_snapshot where id = :i"), {"i": victim.id})
        db.commit()
        try:
            assert not S.verify_chain(db)["intact"]
        finally:
            db.execute(M.ScoreSnapshot.__table__.insert().values(**row))
            db.commit()
        assert S.verify_chain(db)["intact"]


def test_orm_refuses_delete_and_edit(client):
    with SessionLocal() as db:
        sn = db.execute(select(M.ScoreSnapshot).limit(1)).scalars().first()
        sn.composite = 1.0
        with pytest.raises(Exception):
            db.commit()
        db.rollback()
        sn = db.execute(select(M.ScoreSnapshot).limit(1)).scalars().first()
        db.delete(sn)
        with pytest.raises(Exception):
            db.commit()
        db.rollback()


def test_new_snapshot_extends_the_chain_and_supersedes(client):
    with SessionLocal() as db:
        before = db.execute(select(M.ScoreSnapshot.digest).where(M.ScoreSnapshot.digest.is_not(None)).order_by(M.ScoreSnapshot.id.desc())).scalars().first()
        m = taxonomy.MATERIALS["tin"]
        old = m["substitution_difficulty"]
        m["substitution_difficulty"] = 1.2
        try:
            r = S.publish_all(db)
        finally:
            m["substitution_difficulty"] = old
        assert r["created"] == ["tin"]
        new = S.latest(db, "tin")
        assert new.prev_digest == before
        assert S.verify_chain(db)["intact"]
        S.publish_all(db)              # back to the original inputs: a new entry, never an edit
        assert S.verify_chain(db)["intact"]


def test_payload_names_versions_and_events(client):
    with SessionLocal() as db:
        p = S.latest(db, "cobalt").payload
        assert p["formula_version"] == "1.1" and p["severity_table_version"] and "events" in p


def test_unknown_formula_version_is_refused():
    with SessionLocal() as db:
        p = dict(S.latest(db, "cobalt").payload, formula_version="9.9")
        with pytest.raises(ValueError):
            S.recompute(p)
