"""Mississippi DFA Contract Bid Search — source descriptor.

Official portal: https://www.ms.gov/dfa/contract_bid_search  (MS Dept of Finance
& Administration, on the official ms.gov domain). Public / logged-off. The bid
grid is backed by a jQuery DataTables 1.9 server-side endpoint discovered from the
page's own init script:

    POST /dfa/contract_bid_search/Bid/BidData?AppId=1
    - requires a session cookie (set automatically by GETting the Bid page; NO login)
    - body = DataTables 1.9 server-side params (sEcho/iColumns/mDataProp_*/...)
    - returns JSON: { iTotalRecords, aaData: [ {Agency, BidNumber, BidDescription,
      BidStatus, AdvertiseDate, SubmissionDate, ProcurementCategoryDescription,
      BidID, PDFUrl, Attachments[], ... } ] }

PII note (verified): records also carry BuyerName/BuyerEmail/BuyerPhone/BuyerFax.
These are DISCRETE, droppable fields -> strip them; the rest is pure solicitation
data, so the source stays CLEAR.
"""

BASE = "https://www.ms.gov/dfa/contract_bid_search"

# DataTables 1.9 server-side params (the 9 grid columns, from the page's init).
_COLS = ["Agency", "BidNumber", "ObjectID", "VerNumber", "BidStatus",
         "AdvertiseDate", "SubmissionDate", "OpeningDate", "BidID"]


def _datatables_body(start=0, length=10):
    body = {"sEcho": "1", "iColumns": str(len(_COLS)), "sColumns": "",
            "iDisplayStart": str(start), "iDisplayLength": str(length),
            "iSortingCols": "0", "sSearch": "", "bRegex": "false"}
    for i, c in enumerate(_COLS):
        body[f"mDataProp_{i}"] = c
        body[f"sSearch_{i}"] = ""
        body[f"bRegex_{i}"] = "false"
        body[f"bSearchable_{i}"] = "true"
        body[f"bSortable_{i}"] = "true"
    return body


import re as _re
from datetime import datetime, time as _dtime, timezone as _tz
from zoneinfo import ZoneInfo

# Mississippi is US Central. zoneinfo resolves CDT(-05:00)/CST(-06:00) per date.
CENTRAL = ZoneInfo("America/Chicago")

# Status values the API emits (from the live Status dropdown). Anything outside
# this set is LOGGED, not silently served (see scraper.normalize).
STATUS_ENUM = {"Open", "Closed", "Awarded", "Archived"}

# Every input field we have ever seen. A new key -> log it (possible drift).
KNOWN_FIELDS = {
    "ExtensionData", "AdditionalInfo", "AdvertiseDate", "AdvertiseTime", "Agency",
    "AgencyAddress", "AgencyAddress2", "AgencyCity", "AgencyNumber", "AgencyState",
    "AgencyZip", "Attachments", "AwardAmount", "AwardDate", "AwdVendor",
    "BidDescription", "BidID", "BidNumber", "BidStatus", "BidType", "BuyerEmail",
    "BuyerFax", "BuyerName", "BuyerPhone", "ContractStatus", "FundingSource",
    "Items", "ObjectID", "OpeningDate", "OpeningTime", "PDFUrl",
    "ProcurementCategoryDescription", "ProcurementCategoryID",
    "SubProcurementCategoryDescription", "SubProcurementCategoryID",
    "SubmissionDate", "SubmissionTime", "Vendor", "VendorNumber", "VerNumber",
}

# Hard PII boundary: these may NEVER appear in served output (enforced in code).
FORBIDDEN_OUTPUT_KEYS = {"buyername", "buyeremail", "buyerphone", "buyerfax",
                         "agencycontact", "additionalinfo", "contact"}


# Machine-readable schema contract (drives the source-agnostic monitor). This is
# the structured form of sources/mississippi_schema_contract.md.
CONTRACT = {
    "record_path": "aaData",
    "min_records": 1,
    "count_drop_threshold": 0.5,          # >50% below trailing baseline -> ESCALATE
    "status_enum": STATUS_ENUM,
    "status_raw_field": "BidStatus",
    # served field -> raw field(s) it depends on, plus the expected value SHAPE
    # (used both to detect shape drift and to score re-derivation candidates).
    "load_bearing": {
        "solicitation_id": {"raw": ["BidNumber"], "shape": "ident"},
        "title": {"raw": ["BidDescription"], "shape": "text"},
        "agency": {"raw": ["Agency"], "shape": "text", "allow_empty": True},
        "category": {"raw": ["ProcurementCategoryDescription"], "shape": "text"},
        "posted_date": {"raw": ["AdvertiseDate"], "shape": "epoch"},
        "due_date": {"raw": ["SubmissionDate"], "shape": "epoch"},
        "status": {"raw": ["BidStatus"], "shape": "enum"},
        "document_links": {"raw": ["PDFUrl"], "shape": "url"},
    },
    # raw fields whose values flow into served output -> scanned by the PII tripwire
    "served_raw_text_fields": ["BidDescription", "Agency",
                               "ProcurementCategoryDescription",
                               "SubProcurementCategoryDescription"],
    # known PII fields: EXPECTED here and stripped at the boundary -> NOT a tripwire
    "pii_known_fields": set(FORBIDDEN_OUTPUT_KEYS) | {"buyername", "buyeremail",
                                                      "buyerphone", "buyerfax"},
    "url_field_names": {"pdfurl", "url"},
    "id_field_names": {"objectid", "bidid", "agencynumber", "vendornumber",
                       "procurementcategoryid", "subprocurementcategoryid"},
}


def _epoch_ms(s):
    m = _re.search(r"/Date\((-?\d+)\)/", s or "")
    return int(m.group(1)) if m else None


def _parse_time(s):
    if not s:
        return None
    m = _re.match(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$", str(s))
    if not m:
        return None
    # NB: 00:00:00 is a REAL value here — the live site renders it as "12:00 AM"
    # (verified against the Details page), so we keep it rather than dropping it.
    return _dtime(int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def _datetime_central(date_field, time_field):
    """Combine a /Date()/ epoch (midnight Central of the day) with a separate
    HH:MM:SS Central time into a single DST-correct, offset-explicit ISO string.
    Returns (iso_string_or_None, has_time_bool, raw_date, raw_time)."""
    ms = _epoch_ms(date_field)
    raw_date = date_field
    raw_time = time_field
    if ms is None:
        return None, False, raw_date, raw_time
    day = datetime.fromtimestamp(ms / 1000, tz=_tz.utc).astimezone(CENTRAL).date()
    t = _parse_time(time_field)
    if t is None:
        # date known, time not specified — store date-only (no fake midnight)
        return day.isoformat(), False, raw_date, raw_time
    dt = datetime.combine(day, t, tzinfo=CENTRAL)   # zoneinfo applies CDT/CST
    return dt.isoformat(), True, raw_date, raw_time


def _document_links(rec):
    links = []
    if rec.get("PDFUrl"):
        links.append({"label": "Solicitation PDF", "url": rec["PDFUrl"]})
    for a in (rec.get("Attachments") or []):
        if a.get("Url"):
            links.append({"label": a.get("Description") or "Attachment",
                          "url": a["Url"]})
    return links


def map_record(rec):
    """Map one raw MS bid record to the served target schema.

    PII is enforced at THIS boundary: output is assembled from an allowlist only;
    Buyer*/AdditionalInfo are never read into it; a final assertion hard-fails if
    any contact-shaped key slips through.
    """
    due_iso, due_has_time, due_rawd, due_rawt = _datetime_central(
        rec.get("SubmissionDate"), rec.get("SubmissionTime"))
    posted_iso, _, _, _ = _datetime_central(
        rec.get("AdvertiseDate"), rec.get("AdvertiseTime"))

    bid_id = rec.get("BidID")
    out = {
        "source": SOURCE["name"],
        "source_url": f"{BASE}/Bid/Details/{bid_id}" if bid_id else SOURCE["official_url"],
        "solicitation_id": rec.get("BidNumber"),
        "title": (rec.get("BidDescription") or "").strip(),
        "agency": (rec.get("Agency") or "").strip() or "Statewide",
        "category": rec.get("ProcurementCategoryDescription"),
        "sub_category": rec.get("SubProcurementCategoryDescription"),
        "bid_type": rec.get("BidType"),
        "posted_date": posted_iso,
        "due_date": due_iso,                 # ISO-8601, Central offset explicit
        "due_has_time": due_has_time,        # False => date-only (no closing time given)
        "due_timezone": "America/Chicago",
        "status": _normalize_status(rec.get("BidStatus")),
        "estimated_value": _money(rec.get("AwardAmount")),   # award-time only; ~always None
        "document_links": _document_links(rec),
        # audit trail (raw vendor values, for drift/debug; not PII)
        "_raw_submission_date": due_rawd,
        "_raw_submission_time": due_rawt,
        "_bid_id": bid_id,
    }
    _assert_no_pii(out)
    return out


def _normalize_status(s):
    return s if s in STATUS_ENUM else f"UNKNOWN:{s}"


def _money(v):
    if v in (None, "", 0, "0"):
        return None
    try:
        return float(str(v).replace("$", "").replace(",", ""))
    except ValueError:
        return None


# Real emails / formatted phones only — NOT a bare "@" (titles use "@ 9:00 AM"
# to mean "at", which must not be mistaken for an email and crash the feed).
_CONTACT_VALUE_RE = _re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b")


def _assert_no_pii(out):
    for k, v in out.items():
        kl = k.lower()
        if any(bad in kl for bad in FORBIDDEN_OUTPUT_KEYS):
            raise AssertionError(f"PII boundary violation: forbidden key {k!r} in output")
    # free-text served fields must not carry contact PII
    for k in ("title", "category", "agency"):
        val = out.get(k) or ""
        if _CONTACT_VALUE_RE.search(val):
            raise AssertionError(
                f"PII boundary violation: contact-shaped value in served field "
                f"{k!r}: {val[:60]!r}")


SOURCE = {
    "name": "Mississippi DFA Contract Bid Search",
    "host": "www.ms.gov",
    "level": "state",          # SLED: state / local / education
    "official_url": f"{BASE}/Bid",

    # robots.txt: every data path the scraper will hit (tested against our UA).
    "robots_paths": [
        "/dfa/contract_bid_search/Bid",
        "/dfa/contract_bid_search/Bid/BidData",
        "/dfa/contract_bid_search/Bid/Details",
    ],

    # Human page used to detect a login wall (auth redirect / password form).
    "data_page_url": f"{BASE}/Bid",

    # How to fetch a real SAMPLE of records (replicates the captured API).
    "sample": {
        "session_url": f"{BASE}/Bid",   # GET first -> sets the 'mssp' session cookie
        "method": "POST",
        "url": f"{BASE}/Bid/BidData?AppId=1",
        "body": _datatables_body(0, 10),
        "headers": {
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": f"{BASE}/Bid",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        },
        "record_path": "aaData",        # where the records live in the JSON
    },

    # PII handling.
    #  - pii_strip_fields: dropped wholesale before storing/serving. Includes the
    #    discrete Buyer* contact fields AND AdditionalInfo (a free-text notes field
    #    we do NOT serve, which carries officer names/emails/phones).
    #  - keep_text_fields: free-text we DO serve (title/category) — must be clean,
    #    else the source ESCALATES.
    #  - url_fields: document links (not PII; never phone/ID false-positives).
    "pii_strip_fields": ["BuyerName", "BuyerEmail", "BuyerPhone", "BuyerFax",
                         "AgencyContact", "AdditionalInfo"],
    "keep_text_fields": ["BidDescription", "ProcurementCategoryDescription",
                         "SubProcurementCategoryDescription", "Agency"],
    "url_fields": ["PDFUrl", "Url"],
}
