"""UK Contracts Finder (OCDS) — source descriptor + fetch + normalize.

Official Cabinet Office OCDS 1.1 API (Open Government Licence v3.0, commercial OK):
    GET https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search
    - no auth for published notices; data key `releases[]`; 100/page;
      cursor pagination via links.next; orderBy=-publishedDate.

We FLATTEN each OCDS release into a flat raw dict (mirroring the MS aaData row
shape) so the EXISTING store.py / monitor.py / scraper.normalize consume it
unchanged. external_id = ocid (shared across a procurement's tender+award
releases, so change-tracking groups them).

PII boundary (mandatory — email is in 100% of records): DROP
parties[].contactPoint.email/.name/.telephone AND drop tender.description
entirely (it carries emails in ~5%). KEEP buyer.name (organisation only).
"""
import gzip
import json
import re as _re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE = "https://www.contractsfinder.service.gov.uk"
SEARCH = BASE + "/Published/Notices/OCDS/Search"
UA = ("SLEDFeedBot/0.1 (+https://github.com/sled-feed; public government "
      "procurement aggregator; OGL v3.0 data)")

# OCDS tender.status values we expect; anything else -> monitor ESCALATE.
STATUS_ENUM = {"planning", "planned", "active", "cancelled", "unsuccessful",
               "complete", "withdrawn"}

# Flat raw keys produced by fetch() (what store/monitor/map_record see).
KNOWN_FIELDS = {
    "ocid", "notice_id", "tag", "tender_status", "title", "description",
    "buyer_name", "cpv_id", "cpv_desc", "published_date", "deadline",
    "value_amount", "value_currency", "document_urls",
    "contact_name", "contact_email", "contact_telephone",
}

# Hard PII boundary: may NEVER appear in served output.
FORBIDDEN_OUTPUT_KEYS = {"contact_name", "contact_email", "contact_telephone",
                         "description", "contactpoint", "email", "telephone"}

# Machine-readable schema contract (drives the source-agnostic monitor).
CONTRACT = {
    "record_path": "releases",
    "min_records": 1,
    "count_drop_threshold": 0.5,
    "status_enum": STATUS_ENUM,
    "status_raw_field": "tender_status",
    "load_bearing": {
        "solicitation_id": {"raw": ["ocid"], "shape": "ident"},
        "title": {"raw": ["title"], "shape": "text"},
        "agency": {"raw": ["buyer_name"], "shape": "text", "allow_empty": True},
        "category": {"raw": ["cpv_desc"], "shape": "text", "allow_empty": True},
        "posted_date": {"raw": ["published_date"], "shape": "text"},
        "due_date": {"raw": ["deadline"], "shape": "text", "allow_empty": True},
        "status": {"raw": ["tender_status"], "shape": "enum"},
        "document_links": {"raw": ["document_urls"], "shape": "list"},
    },
    "served_raw_text_fields": ["title", "buyer_name", "cpv_desc"],
    "pii_known_fields": {"contact_name", "contact_email", "contact_telephone",
                         "description"},
    "url_field_names": {"document_urls", "source_url", "url"},
    "id_field_names": {"ocid", "notice_id", "cpv_id"},
}


# ---------------------------------------------------------------- fetch / page
def _get(url, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept": "application/json",
                "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"CF fetch failed after {retries}: {last}")


def _iso(s):
    """Normalize an OCDS datetime to ISO-8601 with explicit tz (or None)."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return s


def _notice_guid(rel_id):
    m = _re.match(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                  r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", rel_id or "")
    return m.group(0) if m else None


def _flatten(rel):
    """OCDS release -> flat raw dict (PII fields kept here; dropped at map_record)."""
    t = rel.get("tender") or {}
    cls = t.get("classification") or {}
    val = t.get("value") or {}
    docs = [d.get("url") for d in (t.get("documents") or []) if d.get("url")]
    # contact PII: first party with a contactPoint
    cp = {}
    for p in (rel.get("parties") or []):
        if p.get("contactPoint"):
            cp = p["contactPoint"]
            break
    ocid = rel.get("ocid")
    if not ocid:
        return None
    return {
        "ocid": ocid,
        "notice_id": _notice_guid(rel.get("id") or ""),
        "tag": ",".join(rel.get("tag") or []),
        "tender_status": t.get("status"),
        "title": (t.get("title") or "").strip(),
        "description": t.get("description"),                 # PII-bearing; dropped
        "buyer_name": ((rel.get("buyer") or {}).get("name") or "").strip(),
        "cpv_id": cls.get("id"),
        "cpv_desc": cls.get("description"),
        "published_date": _iso(rel.get("date")),
        "deadline": _iso((t.get("tenderPeriod") or {}).get("endDate")),
        "value_amount": val.get("amount"),
        "value_currency": val.get("currency"),
        "document_urls": docs,
        "contact_name": cp.get("name"),                      # PII; dropped
        "contact_email": cp.get("email"),                    # PII; dropped
        "contact_telephone": cp.get("telephone"),            # PII; dropped
    }


def fetch(max_pages=5, page_pause=0.6):
    """Page recent published notices (newest first). Returns flat raw records,
    deduped by ocid (latest release kept)."""
    url = SEARCH + "?orderBy=-publishedDate"
    out = {}
    for _ in range(max_pages):
        data = _get(url)
        for rel in (data.get("releases") or []):
            f = _flatten(rel)
            if not f:
                continue
            o = f["ocid"]
            if o not in out or (f["published_date"] or "") > (out[o]["published_date"] or ""):
                out[o] = f
        nxt = (data.get("links") or {}).get("next")
        if not nxt:
            break
        url = nxt
        time.sleep(page_pause)
    return list(out.values())


# ---------------------------------------------------------------- normalize
def _map_status(tender_status, tag):
    if "award" in (tag or ""):
        return "Awarded"
    if tender_status in ("active", "planning", "planned"):
        return "Open"
    if tender_status == "complete":
        return "Closed"
    if tender_status in ("cancelled", "unsuccessful", "withdrawn"):
        return "Closed"
    return f"UNKNOWN:{tender_status}"


# Real emails / formatted phones only — NOT a bare "@" (free-text can contain
# "@ 9am" etc., which must not be mistaken for an email and crash the feed).
_CONTACT_VALUE_RE = _re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b")


def _assert_no_pii(out):
    for k in out:
        if any(bad in k.lower() for bad in FORBIDDEN_OUTPUT_KEYS):
            raise AssertionError(f"PII boundary violation: forbidden key {k!r}")
    for k in ("title", "agency", "category"):
        v = out.get(k) or ""
        if not str(v).startswith("http") and _CONTACT_VALUE_RE.search(str(v)):
            raise AssertionError(f"PII boundary violation: contact-shaped value in "
                                 f"{k!r}: {str(v)[:60]!r}")


def map_record(rec):
    """Flat raw -> served target schema (same shape as MS). PII dropped here."""
    guid = rec.get("notice_id")
    src_url = f"{BASE}/notice/{guid}" if guid else SOURCE["official_url"]
    dl = rec.get("deadline")
    has_time = bool(dl and "T" in dl and not dl[11:19].startswith("00:00:00"))
    out = {
        "source": SOURCE["name"],
        "source_url": src_url,
        "solicitation_id": rec.get("ocid"),
        "title": rec.get("title") or "",
        "agency": rec.get("buyer_name") or "Unknown buyer",
        "category": rec.get("cpv_desc"),
        "sub_category": rec.get("cpv_id"),
        "bid_type": rec.get("tag") or None,
        "posted_date": rec.get("published_date"),
        "due_date": dl,                                  # ISO-8601 w/ explicit tz
        "due_has_time": has_time,
        "due_timezone": "Europe/London",
        "status": _map_status(rec.get("tender_status"), rec.get("tag")),
        "estimated_value": rec.get("value_amount"),
        "value_currency": rec.get("value_currency"),     # GBP etc. (UK has value)
        "document_links": [{"label": "Notice document", "url": u}
                           for u in (rec.get("document_urls") or [])],
        "_notice_guid": guid,
    }
    _assert_no_pii(out)
    return out


SOURCE = {
    "name": "UK Contracts Finder (OCDS)",
    "host": "www.contractsfinder.service.gov.uk",
    "level": "national",
    "official_url": f"{BASE}/Search",
    "db_path": "uk_feed.db",
    "kv_store_name": "uk-contractsfinder-state",

    "robots_paths": ["/Published/Notices/OCDS/Search", "/notice"],
    "data_page_url": SEARCH + "?orderBy=-publishedDate",
    "sample": {
        "method": "GET",
        "url": SEARCH + "?orderBy=-publishedDate",
        "headers": {"Accept": "application/json"},
        "record_path": "releases",
    },
    # clearance-filter PII config (separate from the monitor CONTRACT above)
    "pii_strip_fields": ["email", "telephone", "name", "contactpoint", "description"],
    "keep_text_fields": ["title"],
    "url_fields": ["url", "uri", "document_urls"],
}
