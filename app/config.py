"""Settings from environment variables. Secrets are never committed."""
import os


def _b(name, default):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _db_url():
    url = os.environ.get("DATABASE_URL", "sqlite:///./mse.db")
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class Settings:
    database_url = _db_url()
    env = os.environ.get("APP_ENV", "development")
    base_url = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")
    admin_password = os.environ.get("ADMIN_PASSWORD", "")
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    claude_model = os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")
    classifier_mode = os.environ.get("CLASSIFIER_MODE", "auto")           # auto | lexical | claude
    extractor_mode = os.environ.get("EXTRACTOR_MODE", "auto")             # auto | keyword | claude
    claude_daily_call_cap = int(os.environ.get("CLAUDE_DAILY_CALL_CAP", "200"))
    claude_monthly_call_cap = int(os.environ.get("CLAUDE_MONTHLY_CALL_CAP", "3000"))
    # Event layer. Shadow mode computes events and publishes nothing. Go-live needs the 300-document test.
    publish_events = _b("PUBLISH_EVENTS", False)
    launch_status = os.environ.get("LAUNCH_STATUS", "preview")             # preview | live
    indicative_in_sectors = _b("INDICATIVE_IN_SECTORS", True)
    indicative_alerts = _b("INDICATIVE_ALERTS", False)
    rate_per_minute_ip = int(os.environ.get("RATE_PER_MINUTE_IP", "60"))
    rate_assess_per_minute_ip = int(os.environ.get("RATE_ASSESS_PER_MINUTE_IP", "20"))
    max_watchlist = int(os.environ.get("MAX_WATCHLIST", "25"))
    session_days = int(os.environ.get("SESSION_DAYS", "90"))
    secure_cookies = _b("SECURE_COOKIES", os.environ.get("APP_ENV", "development") == "production")
    stale_days_events = int(os.environ.get("EVENT_FEED_STALE_DAYS", "7"))
    contact = os.environ.get("CONTACT_URL", "")


settings = Settings()
