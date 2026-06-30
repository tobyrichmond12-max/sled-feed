#!/usr/bin/env python3
"""
store.py — SQLite storage with UPSERT + change detection + history for the SLED feed.

Design:
  - One row per (source, solicitation_id).  first_seen / last_seen tracked.
  - Upsert, NOT skip-if-seen. On reappearance, LOAD-BEARING field changes (per the
    schema contract: title, agency, category, posted_date, due_date, status,
    document_links) update the row AND write a change_log row (old->new). These
    change events are the product (deadline-extended / newly-awarded / addendum).
  - INCIDENTAL fields (sub_category, bid_type, estimated_value, ...) update silently.
  - Idempotent: re-running on identical data writes zero change_log rows.
  - PII boundary re-asserted at WRITE time (belt and suspenders): a row carrying a
    Buyer*/AdditionalInfo/contact-shaped field is REJECTED before it can touch disk,
    even if the mapper upstream regressed.
"""
import json
import re
import sqlite3
from datetime import datetime, timezone

DB_PATH = "sled_feed.db"

# Per sources/mississippi_schema_contract.md
LOAD_BEARING = ["title", "agency", "category", "posted_date", "due_date",
                "status", "document_links"]
INCIDENTAL = ["sub_category", "bid_type", "estimated_value", "due_has_time",
              "due_timezone", "source_url"]
STORED_COLS = ["source", "solicitation_id"] + LOAD_BEARING + INCIDENTAL

# --- write-time PII boundary (independent of the mapper) ---------------------
_FORBIDDEN_KEYS = ("buyername", "buyeremail", "buyerphone", "buyerfax",
                   "agencycontact", "additionalinfo", "contact")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[-.\s])?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)")


def assert_write_clean(rec):
    for k in rec:
        if any(b in k.lower() for b in _FORBIDDEN_KEYS):
            raise ValueError(f"PII write-boundary: forbidden key {k!r} rejected")
    # scan served scalar text (skip URLs / document_links — file links, not PII)
    for f in ("title", "agency", "category", "sub_category", "source_url"):
        v = str(rec.get(f) or "")
        if v.lower().startswith(("http://", "https://")):
            continue
        if _EMAIL_RE.search(v) or _PHONE_RE.search(v):
            raise ValueError(f"PII write-boundary: contact-shaped value in {f!r}: {v[:60]!r}")


# --- canonicalization for stable comparisons ---------------------------------
def _canon(field, value):
    if field == "document_links":
        items = value if isinstance(value, list) else (json.loads(value or "[]"))
        items = sorted(items, key=lambda d: (d.get("url", ""), d.get("label", "")))
        return json.dumps(items, sort_keys=True, ensure_ascii=False)
    if value is None:
        return ""
    return str(value)


def _store_value(field, value):
    if field == "document_links":
        return _canon(field, value)        # store canonical JSON
    return value


# --- schema ------------------------------------------------------------------
def init_db(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS solicitations (
            {', '.join(c + ' TEXT' for c in STORED_COLS)},
            first_seen TEXT, last_seen TEXT,
            PRIMARY KEY (source, solicitation_id)
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS change_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT, solicitation_id TEXT,
            field TEXT, old_value TEXT, new_value TEXT, changed_at TEXT
        )""")
    conn.commit()
    return conn


# --- upsert ------------------------------------------------------------------
def upsert(conn, records, now=None):
    now = now or datetime.now(timezone.utc).isoformat()
    stats = {"inserted": 0, "updated": 0, "unchanged": 0, "changes": 0, "rejected": 0}
    cur = conn.cursor()
    for rec in records:
        try:
            assert_write_clean(rec)
        except ValueError as e:
            stats["rejected"] += 1
            cur.execute("INSERT INTO change_log(source,solicitation_id,field,old_value,new_value,changed_at)"
                        " VALUES(?,?,?,?,?,?)",
                        (rec.get("source"), rec.get("solicitation_id"), "__REJECTED__",
                         "", str(e), now))
            continue
        key = (rec["source"], rec["solicitation_id"])
        row = cur.execute("SELECT * FROM solicitations WHERE source=? AND solicitation_id=?",
                          key).fetchone()
        cols = [d[0] for d in cur.description] if row else None
        if row is None:
            vals = [rec.get("source"), rec.get("solicitation_id")]
            vals += [_store_value(f, rec.get(f)) for f in LOAD_BEARING + INCIDENTAL]
            vals += [now, now]
            cur.execute(f"INSERT INTO solicitations({', '.join(STORED_COLS)},first_seen,last_seen)"
                        f" VALUES({','.join('?' * (len(STORED_COLS) + 2))})", vals)
            stats["inserted"] += 1
            continue
        existing = dict(zip(cols, row))
        changes = []
        for f in LOAD_BEARING:                       # change-tracked
            old, new = existing.get(f), _store_value(f, rec.get(f))
            if _canon(f, old) != _canon(f, new):
                changes.append((f, old, new))
        # apply update (load-bearing + incidental), bump last_seen, keep first_seen
        set_cols = LOAD_BEARING + INCIDENTAL
        set_vals = [_store_value(f, rec.get(f)) for f in set_cols]
        cur.execute(f"UPDATE solicitations SET {', '.join(c+'=?' for c in set_cols)},"
                    f" last_seen=? WHERE source=? AND solicitation_id=?",
                    set_vals + [now, rec["source"], rec["solicitation_id"]])
        for f, old, new in changes:
            cur.execute("INSERT INTO change_log(source,solicitation_id,field,old_value,new_value,changed_at)"
                        " VALUES(?,?,?,?,?,?)",
                        (rec["source"], rec["solicitation_id"], f, old, new, now))
        if changes:
            stats["updated"] += 1
            stats["changes"] += len(changes)
        else:
            stats["unchanged"] += 1
    conn.commit()
    return stats


def main():
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "mississippi"
    records = json.load(open(f"normalized_{name}.json"))
    conn = init_db()
    stats = upsert(conn, records)
    print("upsert stats:", stats)
    n = conn.execute("SELECT COUNT(*) FROM solicitations").fetchone()[0]
    print("rows in solicitations:", n)
    print("change_log rows:", conn.execute("SELECT COUNT(*) FROM change_log").fetchone()[0])


if __name__ == "__main__":
    main()
