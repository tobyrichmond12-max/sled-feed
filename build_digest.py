#!/usr/bin/env python3
"""Phase-0 weekly concierge digest, built from the EXISTING sled_feed.db (read-only).
Prints three paste-ready sections for the hand-sent Mississippi janitorial email.
No Postgres, no app, no email-sending. Run: python3 build_digest.py"""
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

DB = sys.argv[1] if len(sys.argv) > 1 else "sled_feed.db"
CT = ZoneInfo("America/Chicago")
SYNONYMS = ["janitorial", "custodial", "cleaning", "housekeeping",
            "building services", "floor care", "porter", "sanitation"]
EXCLUDES = ["dry clean", "street sweep", "sewer", "pool"]
STRONG = ["janitorial", "custodial"]           # a hit on only weaker terms => flag
NOW = datetime.now(timezone.utc)
WEEK_AGO = NOW - timedelta(days=7)
HORIZON = NOW + timedelta(days=14)


def janitorial(title, category):
    """Return None if not a match, else True/False for 'weak match' (verify)."""
    text = f"{title or ''} {category or ''}".lower()
    if not any(s in text for s in SYNONYMS):
        return None
    if any(x in text for x in EXCLUDES):
        return None
    return not any(s in text for s in STRONG)   # weak = no janitorial/custodial term


def parse(ts):
    try:
        return datetime.fromisoformat(ts) if ts else None
    except ValueError:
        return None


def due_fmt(s):
    dt = parse(s)
    if dt is None:
        return s or "(no due date)"
    if len(s) <= 10:                            # date-only
        return dt.strftime("%m/%d/%Y")
    return dt.astimezone(CT).strftime("%m/%d/%Y at %I:%M %p") + " CT"


def bid_line(r, weak):
    agency = (r["agency"] or "").strip() or "Statewide"
    flag = "  [WEAK MATCH — verify before including]" if weak else ""
    return (f"• {r['title']}\n"
            f"  {agency} — due {due_fmt(r['due_date'])} — Bid {r['solicitation_id']}\n"
            f"  {r['source_url']}{flag}")


conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
matched = {}                                     # (source, solicitation_id) -> (row, weak)
for r in conn.execute("SELECT * FROM solicitations"):
    weak = janitorial(r["title"], r["category"])
    if weak is not None:
        matched[(r["source"], r["solicitation_id"])] = (r, weak)

new_week, closing = [], []
for r, weak in matched.values():
    if r["status"] != "Open":
        continue
    fs, due = parse(r["first_seen"]), parse(r["due_date"])
    if fs is not None and fs >= WEEK_AGO:
        new_week.append((r, weak))              # "new this week"
    elif due is not None and NOW <= due <= HORIZON:
        closing.append((r, weak))               # closing soon (and not already 'new')
new_week.sort(key=lambda x: parse(x[0]["due_date"]) or NOW)
closing.sort(key=lambda x: parse(x[0]["due_date"]) or NOW)

print(f"\n# Mississippi janitorial digest — week of {datetime.now(CT):%m/%d/%Y}\n")
print("=" * 64)
print("SECTION A  —  NEW THIS WEEK (open janitorial bids)")
print("=" * 64)
print("\n".join(bid_line(r, w) for r, w in new_week) or "None new this week.")

print("\n" + "=" * 64)
print("SECTION A  —  CLOSING SOON (next 14 days)")
print("=" * 64)
print("\n".join(bid_line(r, w) for r, w in closing) or "None closing in the next 14 days.")

print("\n" + "=" * 64)
print("SECTION B  —  WHAT CHANGED (last 7 days)")
print("=" * 64)
events = []
for r in conn.execute("SELECT * FROM change_log "
                      "WHERE field IN ('due_date','status','document_links') "
                      "ORDER BY changed_at DESC"):
    ch = parse(r["changed_at"])
    key = (r["source"], r["solicitation_id"])
    if ch is None or ch < WEEK_AGO or key not in matched:
        continue
    title = matched[key][0]["title"]
    if r["field"] == "due_date":
        events.append(f"• Deadline changed: {title} — now due {due_fmt(r['new_value'])}")
    elif r["field"] == "document_links":
        events.append(f"• Addendum / new document posted: {title}")
    elif (r["new_value"] or "") == "Awarded":
        events.append(f"• Awarded: {title}")
    else:
        events.append(f"• Status: {title} — {r['old_value']} → {r['new_value']}")
print("\n".join(events) if events else "No deadline/addendum changes this week.")
print()
