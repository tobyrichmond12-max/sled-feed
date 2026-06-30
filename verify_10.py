#!/usr/bin/env python3
"""
verify_10.py — Phase-2 GATE. Hand-verify 10 normalized MS records against the
LIVE ms.gov site: due date (date+time+tz), agency, status, and that every
document_link resolves to a real PDF. Prints stored-vs-live side by side.

Selection is purposeful: one with attachments, one sole-source, one near its due
date, one awarded, the rest random. If ANY load-bearing field mismatches, the
script prints MISMATCH and exits non-zero (do not proceed to storage).
"""
import json
import re
import subprocess
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from fetcher import fetch_records
from sources import SOURCES

UA = "SLEDFeedBot/0.1 (+https://github.com/sled-feed; public government procurement aggregator)"
CENTRAL = ZoneInfo("America/Chicago")
src = SOURCES["mississippi"]
M = src["module"]


def get(url):
    r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}),
                               timeout=40)
    return r.read().decode("utf-8", "replace")


def strip(html):
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    h = re.sub(r"<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", h)


def live_fields(html):
    t = strip(html)
    sub = re.search(r"Submission Date\s+(\d{2}/\d{2}/\d{4})(?:\s+(\d{1,2}:\d{2}\s*[AP]M))?", t)
    # agency value runs until the next section label ("RFx Description", etc.)
    agency = re.search(r"Agency\s+([A-Z0-9][A-Z0-9 &.,'/()\-]+?)\s+"
                       r"(?:RFx|Description|Buyer|Status|Major|Bid|Procurement|"
                       r"Submission|Opening|Advertise|Contact)", t)
    status = re.search(r"\bStatus\s+(Open|Closed|Awarded|Archived)\b", t)
    # real documents only: the SAP docserver. Exclude portal.magic.ms.gov nav links.
    docs = re.findall(r'href="(https?://SRM\.MAGIC\.MS\.GOV[^"]*DOCSERVER[^"]*)"',
                      html, re.I)
    return {
        "submission": (sub.group(1) + (" " + sub.group(2) if sub and sub.group(2) else "")) if sub else None,
        "agency": agency.group(1).strip() if agency else None,
        "status": status.group(1) if status else None,
        "doc_count": len(set(docs)),
    }


def live_due_to_iso(s):
    """Parse 'MM/DD/YYYY h:mm AM/PM' (or date-only) -> Central ISO, like stored."""
    if not s:
        return None
    s = s.strip()
    try:
        if re.search(r"[AP]M", s):
            dt = datetime.strptime(s, "%m/%d/%Y %I:%M %p")
            return dt.replace(tzinfo=CENTRAL).isoformat()
        d = datetime.strptime(s, "%m/%d/%Y").date()
        return d.isoformat()
    except ValueError:
        return None


DOC_MAGICS = (b"%PDF-", b"PK\x03\x04", b"\xd0\xcf\x11\xe0", b"{\\rtf")  # pdf/office/doc/rtf


def resolve_doc(url):
    """GET the document (curl -k; the magic.ms.gov SAP host omits its intermediate
    cert). A document RESOLVES if HTTP 200 and the body is a real file (known magic
    bytes or a non-HTML content-type) — attachments are PDF/XLSX/DOCX, not just PDF.
    Returns (http_code, content_type, ok)."""
    try:
        out = subprocess.run(
            ["curl", "-sk", "-A", UA, "--max-time", "40", "-o", "/tmp/_d.bin",
             "-w", "%{http_code}|%{content_type}", url],
            capture_output=True, text=True, timeout=50).stdout
        code, ctype = (out.split("|") + ["", ""])[:2]
        with open("/tmp/_d.bin", "rb") as f:
            head = f.read(8)
        is_doc = head.startswith(DOC_MAGICS)
        not_html = bool(ctype) and not ctype.lower().startswith("text/html")
        ok = (code == "200") and (is_doc or not_html)
        return code, ctype, ok
    except Exception as e:  # noqa: BLE001
        return f"ERR({e})", "", False


def pick_targets(open_recs, awarded_recs):
    """raw+mapped pairs. Purposeful 10."""
    pairs = [(r, M.map_record(r)) for r in open_recs]
    picked, seen = [], set()

    def take(pair, why):
        bid = pair[1]["_bid_id"]
        if bid not in seen:
            seen.add(bid)
            picked.append((why, pair))

    # one with the most document links (attachments)
    take(max(pairs, key=lambda p: len(p[1]["document_links"])), "attachments")
    # sole-source
    ss = [p for p in pairs if "sole source" in (p[1]["title"] or "").lower()]
    if ss:
        take(ss[0], "sole-source")
    # nearest due date in the future
    fut = sorted([p for p in pairs if p[1]["due_date"]], key=lambda p: p[1]["due_date"])
    if fut:
        take(fut[0], "near-due")
    # one awarded
    if awarded_recs:
        take((awarded_recs[0], M.map_record(awarded_recs[0])), "awarded")
    # fill to 10 with deterministic "random" (every Nth)
    i = 0
    while len(picked) < 10 and i < len(pairs):
        take(pairs[i * 7 % len(pairs)], "random")
        i += 1
    return picked[:10]


def main():
    open_recs = fetch_records(src)                       # cached Open
    asample = dict(src["sample"])
    asample["url"] = asample["url"].split("&Status")[0] + "&Status=Awarded"
    asrc = {"name": "MS Awarded", "sample": asample}
    awarded_recs = fetch_records(asrc, length=5)

    targets = pick_targets(open_recs, awarded_recs)
    print(f"Hand-verifying {len(targets)} records against live ms.gov\n")
    all_ok = True
    for n, (why, (raw, rec)) in enumerate(targets, 1):
        time.sleep(1.2)
        html = get(rec["source_url"])
        lf = live_fields(html)
        stored_due = rec["due_date"]
        live_due = live_due_to_iso(lf["submission"])
        due_ok = (stored_due == live_due)
        agency_ok = (lf["agency"] or "").upper().startswith((rec["agency"] or "").upper()[:12]) or \
                    (rec["agency"] == "Statewide" and not lf["agency"])
        status_ok = (lf["status"] == rec["status"])
        # resolve every document link
        doc_results = [resolve_doc(d["url"]) for d in rec["document_links"]]
        docs_ok = all(c == "200" and isp for c, _, isp in doc_results) and len(doc_results) > 0

        ok = due_ok and agency_ok and status_ok and docs_ok
        all_ok = all_ok and ok
        print(f"[{n:>2}] {why:<12} {rec['solicitation_id']}  bid={rec['_bid_id']}  -> {'OK' if ok else 'MISMATCH'}")
        print(f"     due    stored={stored_due}  live='{lf['submission']}'->{live_due}  {'ok' if due_ok else 'XXX'}")
        print(f"     agency stored={rec['agency']!r}  live={lf['agency']!r}  {'ok' if agency_ok else 'XXX'}")
        print(f"     status stored={rec['status']!r}  live={lf['status']!r}  {'ok' if status_ok else 'XXX'}")
        print(f"     docs   stored={len(rec['document_links'])} live={lf['doc_count']}  "
              f"resolved={[ (c,isp) for c,_,isp in doc_results]}  {'ok' if docs_ok else 'XXX'}")
    print("\n" + ("ALL 10 MATCH — gate PASSED" if all_ok else "MISMATCH FOUND — STOP, do not proceed to storage"))
    raise SystemExit(0 if all_ok else 2)


if __name__ == "__main__":
    main()
