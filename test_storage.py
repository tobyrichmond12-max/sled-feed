#!/usr/bin/env python3
"""Phase-3 verification: load, idempotency, change-detection, PII write-boundary."""
import copy
import json
import os
import sqlite3
from datetime import datetime, timedelta

import store

DB = "sled_feed.db"
for ext in ("", "-wal", "-shm"):
    if os.path.exists(DB + ext):
        os.remove(DB + ext)

records = json.load(open("normalized_mississippi.json"))
by_id = {r["solicitation_id"]: r for r in records}
conn = store.init_db(DB)


def changelog_count():
    return conn.execute("SELECT COUNT(*) FROM change_log").fetchone()[0]


def dump_changes(since_id=0):
    rows = conn.execute(
        "SELECT solicitation_id,field,old_value,new_value FROM change_log WHERE id>? ORDER BY id",
        (since_id,)).fetchall()
    for sid, field, old, new in rows:
        o = (old[:48] + "…") if old and len(old) > 48 else old
        n = (new[:48] + "…") if new and len(new) > 48 else new
        print(f"    [{field}] {sid}\n        old={o!r}\n        new={n!r}")


print("=" * 64)
print("1) INITIAL LOAD")
s = store.upsert(conn, records)
print("   stats:", s)
n = conn.execute("SELECT COUNT(*) FROM solicitations").fetchone()[0]
print(f"   rows: {n}  (expect 130)")

# PII audit of everything actually stored
cols = [d[1] for d in conn.execute("PRAGMA table_info(solicitations)")]
forbidden_cols = [c for c in cols if any(b in c.lower() for b in store._FORBIDDEN_KEYS)]
contact_hits = 0
for row in conn.execute("SELECT title,agency,category,source_url FROM solicitations"):
    for v in row:
        if v and not str(v).startswith("http") and (store._EMAIL_RE.search(str(v)) or store._PHONE_RE.search(str(v))):
            contact_hits += 1
print(f"   PII audit: forbidden columns={forbidden_cols or 'none'}, contact-shaped values in served text={contact_hits}")

print("=" * 64)
print("2) IDEMPOTENCY — re-run identical data")
before = changelog_count()
s2 = store.upsert(conn, records)
after = changelog_count()
print("   stats:", s2)
print(f"   change_log delta: {after - before}  (expect 0)")
print(f"   IDEMPOTENT: {'YES' if after == before and s2['changes'] == 0 else 'NO'}")

print("=" * 64)
print("3) SIMULATED UPDATES (the valuable events)")
ids = list(by_id)
r_due = copy.deepcopy(by_id[ids[0]])
r_status = copy.deepcopy(by_id[ids[1]])
r_doc = copy.deepcopy(by_id[ids[2]])

old_due = r_due["due_date"]
new_due = (datetime.fromisoformat(old_due) + timedelta(days=7)).isoformat()
r_due["due_date"] = new_due
print(f"   a) extend due_date  {ids[0]}:  {old_due}  ->  {new_due}")

old_status = r_status["status"]
r_status["status"] = "Awarded"
print(f"   b) flip status      {ids[1]}:  {old_status}  ->  Awarded")

r_doc["document_links"] = r_doc["document_links"] + [
    {"label": "Addendum 1", "url": "https://www.ms.gov/dfa/contract_bid_search/addendum1.pdf"}]
print(f"   c) add document     {ids[2]}:  {len(by_id[ids[2]]['document_links'])} -> {len(r_doc['document_links'])} links")

before = changelog_count()
s3 = store.upsert(conn, [r_due, r_status, r_doc])
print("   stats:", s3)
print(f"   new change_log entries: {changelog_count() - before}  (expect 3)")
dump_changes(before)

print("=" * 64)
print("4) INCIDENTAL change updates silently (no change event)")
r_inc = copy.deepcopy(by_id[ids[3]])
print(f"   change bid_type {ids[3]}: {r_inc['bid_type']!r} -> 'CHANGED-TYPE'")
r_inc["bid_type"] = "CHANGED-TYPE"
before = changelog_count()
s4 = store.upsert(conn, [r_inc])
stored_bt = conn.execute("SELECT bid_type FROM solicitations WHERE solicitation_id=?",
                         (ids[3],)).fetchone()[0]
print(f"   stats: {s4} | change_log delta: {changelog_count()-before} (expect 0) | stored bid_type now {stored_bt!r}")

print("=" * 64)
print("5) PII WRITE-BOUNDARY (belt & suspenders)")
# a) forbidden key smuggled in
bad1 = copy.deepcopy(by_id[ids[4]]); bad1["BuyerEmail"] = "officer@agency.ms.gov"
# b) contact value in a served field
bad2 = copy.deepcopy(by_id[ids[5]]); bad2["title"] = "Call John at john.doe@ms.gov / 601-555-1212"
before = changelog_count()
s5 = store.upsert(conn, [bad1, bad2])
print(f"   stats: {s5}  (expect rejected=2)")
# confirm the PII did NOT land
got_email = conn.execute("SELECT title FROM solicitations WHERE solicitation_id=?",
                         (ids[5],)).fetchone()[0]
print(f"   record {ids[5]} title in DB still clean: {'YES' if '@' not in got_email else 'NO'}")
print("   rejection log:")
dump_changes(before)

print("=" * 64)
print("6) SAMPLE STORED RECORD")
row = conn.execute("SELECT * FROM solicitations WHERE solicitation_id=?", (ids[0],)).fetchone()
cols = [d[0] for d in conn.execute("SELECT * FROM solicitations LIMIT 0").description]
rec = dict(zip(cols, row))
rec["document_links"] = json.loads(rec["document_links"])
print(json.dumps({k: rec[k] for k in ("source", "solicitation_id", "title", "agency",
      "due_date", "status", "estimated_value", "first_seen", "last_seen",
      "document_links")}, indent=2)[:1100])

print("=" * 64)
print(f"FINAL: solicitations={conn.execute('SELECT COUNT(*) FROM solicitations').fetchone()[0]}, "
      f"change_log={changelog_count()}")
