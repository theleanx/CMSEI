"""Opt-in alerts when a material's tier changes (or its score moves 5 points or more).

Channels: Slack incoming webhook, Teams webhook (Workflows or connector), or email. Rules:
  * A target is used only after it is confirmed. A webhook is confirmed by a test message it accepts. Email is confirmed by a link.
  * Webhook hosts are checked against an allow-list and must resolve to public addresses. No redirects are followed.
  * A subscription is switched off after 5 failed sends, and unconfirmed ones are purged after 7 days.
  * The manage token is shown once; only its hash is stored. Anyone holding it can delete the subscription.
Sending code is covered by tests with fake transports. It has not been run against live Slack, Teams or an SMTP server.
"""
from __future__ import annotations
import hashlib
import ipaddress
import logging
import secrets
import smtplib
import socket
from email.message import EmailMessage
from urllib.parse import urlparse
import httpx
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .. import models as M
from ..config import settings
from ..engine import taxonomy

log = logging.getLogger("mse.alerts")
MAX_FAILURES = 5
MAX_MATERIALS = 25
# Hosts that Slack and Teams issue webhook URLs on. Teams moved from Office 365 connectors to Workflows (Power Automate), so both are listed.
HOST_SUFFIXES = {"slack": ("hooks.slack.com",),
                 "teams": (".webhook.office.com", ".logic.azure.com", ".powerplatform.com", ".api.powerplatform.com")}


def _hash(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


class AlertError(ValueError):
    pass


def email_enabled() -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def check_webhook(channel: str, url: str, resolve=socket.getaddrinfo) -> str:
    u = urlparse(url.strip())
    if u.scheme != "https" or not u.hostname or u.username or u.password or (u.port not in (None, 443)):
        raise AlertError("The webhook must be a plain https address.")
    host = u.hostname.lower()
    ok = any(host == s.lstrip(".") or host.endswith(s if s.startswith(".") else "." + s) or host == s for s in HOST_SUFFIXES[channel])
    if not ok:
        raise AlertError(f"That is not a {channel.title()} webhook address.")
    try:
        infos = resolve(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        raise AlertError("That address could not be looked up.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise AlertError("That address does not point to a public server.")
    return u.geturl()


def _post(url: str, body: dict) -> bool:
    try:
        r = httpx.post(url, json=body, timeout=8.0, follow_redirects=False)
        return 200 <= r.status_code < 300
    except Exception:
        return False


def _teams_card(title: str, text: str) -> dict:
    return {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard", "version": "1.4",
        "body": [{"type": "TextBlock", "text": title, "weight": "Bolder", "wrap": True}, {"type": "TextBlock", "text": text, "wrap": True}]}}]}


def _payload(channel: str, title: str, text: str) -> dict:
    return {"text": f"*{title}*\n{text}"} if channel == "slack" else _teams_card(title, text)


def _send_email(to: str, subject: str, body: str) -> bool:
    try:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
        msg.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as s:
            if settings.smtp_starttls:
                s.starttls()
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
        return True
    except Exception:
        return False


def deliver(channel: str, target: str, title: str, text: str, post=_post, mail=_send_email) -> bool:
    if channel in ("slack", "teams"):
        return post(target, _payload(channel, title, text))
    return mail(target, title, text)


def subscribe(db: Session, channel: str, target: str, material_ids: list[str], post=_post, mail=_send_email, resolve=socket.getaddrinfo) -> dict:
    if channel not in ("slack", "teams", "email"):
        raise AlertError("Unknown channel.")
    ids = [m for m in dict.fromkeys(material_ids) if m in taxonomy.MATERIALS][:MAX_MATERIALS]
    if not ids:
        raise AlertError("Pick at least one material.")
    target = target.strip()
    if channel == "email":
        if not email_enabled():
            raise AlertError("Email alerts are not switched on for this site.")
        if len(target) > 254 or target.count("@") != 1 or " " in target or "." not in target.split("@")[1]:
            raise AlertError("That does not look like an email address.")
        target = target.lower()
    else:
        target = check_webhook(channel, target, resolve)
    th = _hash(target)
    if db.execute(select(M.AlertSubscription.id).where(M.AlertSubscription.channel == channel, M.AlertSubscription.target_hash == th)).first():
        raise AlertError("That address is already subscribed. Use its manage link to change it.")
    manage, confirm = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    sub = M.AlertSubscription(channel=channel, target=target, target_hash=th, material_ids=ids, confirmed=False,
                              confirm_token_hash=_hash(confirm), manage_token_hash=_hash(manage))
    db.add(sub)
    db.flush()
    names = ", ".join(taxonomy.MATERIALS[i]["name"] for i in ids[:6]) + ("…" if len(ids) > 6 else "")
    if channel == "email":
        link = f"{settings.base_url}/alerts/confirm/{confirm}"
        ok = deliver(channel, target, "Confirm CMSEI alerts", f"Confirm that you want CMSEI tier-change alerts for: {names}.\n\nConfirm: {link}\n\n"
                     f"If you did not ask for this, ignore this message and nothing will be sent.", post, mail)
        if not ok:
            db.rollback()
            raise AlertError("The confirmation email could not be sent.")
        status = "pending_email"
    else:
        ok = deliver(channel, target, "CMSEI alerts connected", f"You will get a message here when the tier changes for: {names}. "
                     f"Manage or stop alerts: {settings.base_url}/alerts/manage/{manage}", post, mail)
        if not ok:
            db.rollback()
            raise AlertError("The test message was not accepted by that webhook, so alerts were not switched on.")
        sub.confirmed, sub.confirm_token_hash = True, None
        status = "active"
    db.commit()
    return {"status": status, "manage_token": manage, "materials": ids}


def confirm(db: Session, token: str) -> bool:
    sub = db.execute(select(M.AlertSubscription).where(M.AlertSubscription.confirm_token_hash == _hash(token))).scalars().first()
    if not sub:
        return False
    sub.confirmed, sub.confirm_token_hash = True, None
    db.commit()
    return True


def by_manage_token(db: Session, token: str) -> M.AlertSubscription | None:
    if not token or len(token) > 100:
        return None
    return db.execute(select(M.AlertSubscription).where(M.AlertSubscription.manage_token_hash == _hash(token))).scalars().first()


def remove(db: Session, token: str) -> bool:
    sub = by_manage_token(db, token)
    if not sub:
        return False
    db.delete(sub)
    db.commit()
    return True


def dispatch(db: Session, changes: list[dict], post=_post, mail=_send_email) -> dict:
    """Send one message per subscription covering all its materials that changed. Returns counts."""
    if not changes:
        return {"sent": 0, "failed": 0}
    by_mat = {c["material_id"]: c for c in changes}
    sent = failed = 0
    for sub in db.execute(select(M.AlertSubscription).where(M.AlertSubscription.confirmed.is_(True), M.AlertSubscription.failures < MAX_FAILURES)).scalars():
        hits = [by_mat[m] for m in sub.material_ids if m in by_mat]
        if not hits:
            continue
        lines = [f"{h['name']}: {h['from_score']} ({h['from_tier']}) to {h['to_score']} ({h['to_tier']})" for h in hits]
        text = "\n".join(lines) + f"\n\nThese are market-level scores, not a statement about your suppliers. Details: {settings.base_url}/materials\n" \
                                  f"Stop alerts: {settings.base_url}/alerts/manage/<your manage link>"
        ok = deliver(sub.channel, sub.target, "CMSEI: supply exposure changed", text, post, mail)
        if ok:
            sub.last_sent_at, sub.failures = M.now(), 0
            sent += 1
        else:
            sub.failures += 1
            failed += 1
    db.commit()
    return {"sent": sent, "failed": failed}


def purge(db: Session) -> int:
    import datetime as dt
    cutoff = M.now() - dt.timedelta(days=7)
    n = db.execute(delete(M.AlertSubscription).where(M.AlertSubscription.confirmed.is_(False), M.AlertSubscription.created_at < cutoff)).rowcount
    n += db.execute(delete(M.AlertSubscription).where(M.AlertSubscription.failures >= MAX_FAILURES)).rowcount
    db.commit()
    return n or 0
