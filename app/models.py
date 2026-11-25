"""Tables (spec 3.3). Privacy by structure: `assessment` has no region, volume or free-text column.
Sessions are stored only as a hash of a random token."""
import datetime as dt
from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, JSON, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def now():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class Material(Base):
    __tablename__ = "material"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    grp: Mapped[str] = mapped_column(String(128))
    record: Mapped[dict] = mapped_column(JSON)
    taxonomy_version: Mapped[str] = mapped_column(String(64))
    signed_off_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    signed_off_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class ScoreSnapshot(Base):
    __tablename__ = "score_snapshot"
    __table_args__ = (UniqueConstraint("prev_digest", name="uq_score_snapshot_prev_digest"),)   # one successor per entry: no forks
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    material_id: Mapped[str] = mapped_column(ForeignKey("material.id"), index=True)
    formula_version: Mapped[str] = mapped_column(String(16))
    taxonomy_version: Mapped[str] = mapped_column(String(64))
    data_as_of: Mapped[str] = mapped_column(String(64))
    source_snapshot: Mapped[dict] = mapped_column(JSON)
    model_version: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(64))
    events_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)               # exact inputs; recompute() must reproduce the result
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    prev_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)   # digest of the entry before this one
    digest: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    concentration: Mapped[float] = mapped_column(Float)
    processing_risk: Mapped[float] = mapped_column(Float)
    substitution_difficulty: Mapped[float] = mapped_column(Float)
    geopolitical_multiplier: Mapped[float] = mapped_column(Float)
    composite: Mapped[float] = mapped_column(Float)
    tier: Mapped[str] = mapped_column(String(16))
    grade: Mapped[str] = mapped_column(String(8))
    uncertainty: Mapped[dict] = mapped_column(JSON)
    citations: Mapped[list] = mapped_column(JSON)
    published_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    superseded_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class Assessment(Base):
    """Only what was resolved. No free text, region or volume."""
    __tablename__ = "assessment"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    material_id: Mapped[str] = mapped_column(ForeignKey("material.id"))
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("score_snapshot.id"))
    recommendation_rule_ids: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class Session(Base):
    __tablename__ = "session"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    last_seen: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class Watchlist(Base):
    __tablename__ = "watchlist"
    __table_args__ = (UniqueConstraint("session_hash", "material_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_hash: Mapped[str] = mapped_column(ForeignKey("session.token_hash"), index=True)
    material_id: Mapped[str] = mapped_column(ForeignKey("material.id"))
    alert_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_seen_snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class WatchlistEvent(Base):
    __tablename__ = "watchlist_event"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlist.id", ondelete="CASCADE"), index=True)
    material_id: Mapped[str] = mapped_column(String(64))
    from_snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_snapshot_id: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))          # tier_change | score_move | threshold
    summary: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class SectorScore(Base):
    __tablename__ = "sector_score"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sector_id: Mapped[str] = mapped_column(String(64), index=True)
    sector_name: Mapped[str] = mapped_column(String(128))
    snapshot_ids: Mapped[list] = mapped_column(JSON)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    top_material_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32))        # scored | not_scored
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    list_version: Mapped[str] = mapped_column(String(64))
    includes_indicative: Mapped[bool] = mapped_column(Boolean, default=False)
    computed_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    superseded_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class EventRecord(Base):
    """Audit log of every candidate event the monitor saw (spec 4.9 item 9). Public."""
    __tablename__ = "event_record"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    material_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    instrument: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stage: Mapped[str | None] = mapped_column(String(16), nullable=True)
    event_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    effective_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_host: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_tier: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extractor: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(64))
    reasons: Mapped[list] = mapped_column(JSON, default=list)     # validator failures
    status: Mapped[str] = mapped_column(String(24), index=True)
    # rejected | pending_corroboration | pending_official_text | qualified | held | active | superseded | expired | removed | shadow_active
    reviewer: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hold_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    held_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_verified: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    verify_failures: Mapped[int] = mapped_column(Integer, default=0)
    shadow: Mapped[bool] = mapped_column(Boolean, default=True)


class Correction(Base):
    """Report a correction. No name or email is collected."""
    __tablename__ = "correction"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    material_id: Mapped[str] = mapped_column(String(64))
    item: Mapped[str] = mapped_column(String(128))
    proposed_value: Mapped[str] = mapped_column(String(255))
    source_link: Mapped[str] = mapped_column(String(512))
    note: Mapped[str] = mapped_column(String(1000), default="")
    status: Mapped[str] = mapped_column(String(16), default="received")   # received | accepted | declined
    decision_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class JobRun(Base):
    __tablename__ = "job_run"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job: Mapped[str] = mapped_column(String(48), index=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")     # running | ok | failed
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class Analytics(Base):
    """Category-level counts only. Never raw input (spec 1.7)."""
    __tablename__ = "analytics_event"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    material_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    method: Mapped[str | None] = mapped_column(String(24), nullable=True)
    session_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Counter(Base):
    """Small keyed counters, for example the daily Claude call budget."""
    __tablename__ = "counter"
    key: Mapped[str] = mapped_column(String(96), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class QuarantinedDocument(Base):
    """A source document held back from the language model because it contained instruction-like text (claim 6)."""
    __tablename__ = "quarantined_document"
    __table_args__ = (UniqueConstraint("content_hash", "url", name="uq_quarantine_doc"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    doc_id: Mapped[str] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(String(512))
    host: Mapped[str] = mapped_column(String(128))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    reasons: Mapped[list] = mapped_column(JSON)


# ---- append-only guard for the snapshot log (claim 5): rows are never deleted, and only superseded_at may change
from sqlalchemy import event, inspect as _inspect


@event.listens_for(ScoreSnapshot, "before_delete")
def _no_delete(mapper, connection, target):
    raise RuntimeError("score_snapshot is append-only: rows cannot be deleted")


@event.listens_for(ScoreSnapshot, "before_update")
def _only_supersede(mapper, connection, target):
    st = _inspect(target)
    for attr in st.mapper.column_attrs:
        if attr.key != "superseded_at" and st.attrs[attr.key].history.has_changes():
            raise RuntimeError(f"score_snapshot is append-only: {attr.key} cannot be changed")
