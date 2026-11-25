"""Anonymous sessions (spec 3.3). The browser holds a random token; the database holds only its SHA-256."""
import hashlib
import secrets
import datetime as dt
from sqlalchemy import select, delete
from sqlalchemy.orm import Session as DbSession
from .. import models as M
from ..config import settings


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create(db: DbSession) -> str:
    token = secrets.token_urlsafe(32)
    db.add(M.Session(token_hash=_hash(token)))
    db.commit()
    return token


def get(db: DbSession, token: str | None) -> str | None:
    """Returns the session hash if the token is valid and fresh, else None."""
    if not token or len(token) > 100:
        return None
    h = _hash(token)
    s = db.get(M.Session, h)
    if not s:
        return None
    if (M.now() - s.last_seen).days > settings.session_days:
        delete_all(db, h)
        return None
    s.last_seen = M.now()
    db.commit()
    return h


def delete_all(db: DbSession, h: str) -> None:
    """Spec 6 (session deletion): removes the session, its watchlist, change indicators and analytics rows."""
    wl = [w.id for w in db.execute(select(M.Watchlist).where(M.Watchlist.session_hash == h)).scalars()]
    if wl:
        db.execute(delete(M.WatchlistEvent).where(M.WatchlistEvent.watchlist_id.in_(wl)))
    db.execute(delete(M.Watchlist).where(M.Watchlist.session_hash == h))
    db.execute(delete(M.Analytics).where(M.Analytics.session_hash == h))
    db.execute(delete(M.Session).where(M.Session.token_hash == h))
    db.commit()


def purge_expired(db: DbSession) -> int:
    cutoff = M.now() - dt.timedelta(days=settings.session_days)
    old = [s.token_hash for s in db.execute(select(M.Session).where(M.Session.last_seen < cutoff)).scalars()]
    for h in old:
        delete_all(db, h)
    return len(old)
