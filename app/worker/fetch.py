"""Document fetchers. Only allowlisted hosts are ever requested (exact host match)."""
from __future__ import annotations
import datetime as dt
import hashlib
import re
from urllib.parse import urlparse
import httpx
from ..engine import taxonomy

UA = "MaterialSupplyExposureIndex-monitor/1.0 (public-data research; contact via site)"
MAX_CHARS = 60000


def host_allowed(url: str) -> bool:
    p = urlparse(url)
    return p.scheme == "https" and p.hostname in taxonomy.ALLOWLIST["hosts"]


def _strip(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", html)).strip()


def get_text(client: httpx.Client, url: str) -> str:
    if not host_allowed(url):
        raise ValueError("host not allowlisted")
    r = client.get(url, headers={"User-Agent": UA}, timeout=20.0, follow_redirects=False)
    r.raise_for_status()
    return _strip(r.text)[:MAX_CHARS]


def federal_register(client: httpx.Client, terms: list[str], days: int = 45) -> list[dict]:
    """US Federal Register API (free, no key). Tier 1: the United States is the issuer."""
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    docs, seen = [], set()
    for term in terms:
        params = {"conditions[term]": term, "conditions[publication_date][gte]": since, "per_page": 10, "order": "newest",
                  "fields[]": ["title", "html_url", "publication_date", "document_number", "raw_text_url", "abstract"]}
        r = client.get("https://www.federalregister.gov/api/v1/documents.json", params=params, headers={"User-Agent": UA}, timeout=20.0)
        r.raise_for_status()
        for it in r.json().get("results", []):
            num = it.get("document_number")
            if not num or num in seen:
                continue
            seen.add(num)
            try:
                text = get_text(client, it["raw_text_url"]) if it.get("raw_text_url") else (it.get("abstract") or "")
            except Exception:
                text = it.get("abstract") or ""
            if not text:
                continue
            docs.append({"id": f"FR-{num}", "host": urlparse(it["html_url"]).hostname, "url": it["html_url"], "pub_date": it["publication_date"],
                         "title": it.get("title", ""), "text": text})
    return docs


def rss(client: httpx.Client, feed_url: str) -> list[dict]:
    """Generic RSS for an allowlisted host. Needs a feed URL added to data/sources_allowlist.json by pull request."""
    from defusedxml import ElementTree as ET
    if not host_allowed(feed_url):
        raise ValueError("host not allowlisted")
    r = client.get(feed_url, headers={"User-Agent": UA}, timeout=20.0)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    docs = []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        if not host_allowed(link):
            continue
        try:
            text = get_text(client, link)
        except Exception:
            continue
        pub = item.findtext("pubDate") or ""
        try:
            from email.utils import parsedate_to_datetime
            d = parsedate_to_datetime(pub).date().isoformat()
        except Exception:
            d = dt.date.today().isoformat()
        docs.append({"id": "RSS-" + hashlib.sha256(link.encode()).hexdigest()[:12], "host": urlparse(link).hostname, "url": link,
                     "pub_date": d, "title": (item.findtext("title") or "")[:200], "text": text})
    return docs


def collect(client: httpx.Client) -> list[dict]:
    docs = []
    for feed in taxonomy.ALLOWLIST["feeds"]:
        if not feed.get("enabled"):
            continue
        if feed["kind"] == "federal_register_api":
            terms = [f"{m['name'].split(' (')[0]} export" for m in taxonomy.MATERIALS.values()]
            docs += federal_register(client, terms)
        elif feed["kind"] == "rss":
            docs += rss(client, feed["url"])
    return docs
