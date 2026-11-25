from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .config import settings

_kw = {"pool_pre_ping": True}
if settings.database_url.startswith("sqlite"):
    _kw["connect_args"] = {"check_same_thread": False}
engine = create_engine(settings.database_url, **_kw)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
