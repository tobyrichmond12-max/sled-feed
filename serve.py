#!/usr/bin/env python3
"""
serve.py — service layer behind the MCP server / Apify Actor.

Three tools: search_opportunities, get_opportunity, list_recent_changes (the
change feed is the differentiator — free portals show current bids, we show what
CHANGED). Every call is:
  - HEALTH-GATED: a source in ESCALATE/STOP (or latched-unhealthy) is NEVER served;
    we return "source_temporarily_unavailable" rather than stale/wrong data.
  - METERED via billing.meter.

estimated_value is intentionally NOT served as a populated/filterable field — this
source does not publish it (documented as "not available from this source").
"""
import json
import os
import sqlite3

import monitor
import store
from billing import meter
from sources import SOURCES

# The deployment serves ONE source, selected by SLED_SOURCE (default mississippi).
# Same code runs the MS or UK Actor; the env var + DB path differ per deployment.
ACTIVE = os.environ.get("SLED_SOURCE", "mississippi")
ACTIVE_SOURCE_NAME = SOURCES[ACTIVE]["name"]
STATUS_ENUM = {"Open", "Closed", "Awarded", "Archived"}

# buyer-facing fields (no PII, no estimated_value, no internal _underscore fields)
SERVED_FIELDS = ["solicitation_id", "title", "agency", "category", "sub_category",
                 "bid_type", "posted_date", "due_date", "due_timezone", "status",
                 "document_links", "source", "source_url", "first_seen", "last_seen"]


def _conn():
    return sqlite3.connect(store.DB_PATH)   # dynamic: actor_main sets it per source


def _healthy(conn, source):
    state, _reason, _latched = monitor.health_of(conn, source)
    return state == "HEALTHY"


def _unavailable(source, conn):
    _state, reason, _l = monitor.health_of(conn, source)
    return {"status": "source_temporarily_unavailable", "source": source,
            "reason": f"source health = {_state}",
            "detail": "We refuse to serve a source flagged unhealthy by the monitor "
                      "rather than return stale or incorrect data. Try again later.",
            "results": []}


def _row_record(row, cols):
    d = dict(zip(cols, row))
    rec = {}
    for f in SERVED_FIELDS:
        v = d.get(f)
        if f == "document_links":
            v = json.loads(v) if v else []
        rec[f] = v
    ev = d.get("estimated_value")
    rec["estimated_value"] = ev
    if ev is None:
        rec["estimated_value_note"] = "not available from this source"
    return rec


def _resolve_state(state):
    # one active source per deployment; the state arg is accepted for API
    # compatibility but does not change which source is served.
    return ACTIVE_SOURCE_NAME


# --------------------------------------------------------------------------
def search_opportunities(state="MS", category=None, keyword=None, status=None,
                         posted_after=None, due_before=None, due_after=None,
                         limit=50, account="anonymous"):
    meter(account, "search_opportunities")
    source = _resolve_state(state)
    if not source:
        return {"status": "unsupported_state", "supported_states": SUPPORTED_STATES,
                "results": []}
    conn = _conn()
    if not _healthy(conn, source):
        return _unavailable(source, conn)
    if status and status not in STATUS_ENUM:
        return {"status": "bad_request",
                "detail": f"status must be one of {sorted(STATUS_ENUM)}", "results": []}

    cols = [c[1] for c in conn.execute("PRAGMA table_info(solicitations)")]
    where, args = ["source = ?"], [source]
    if status:
        where.append("status = ?"); args.append(status)
    if category:
        where.append("category LIKE ?"); args.append(f"%{category}%")
    if keyword:
        where.append("(title LIKE ? OR category LIKE ?)")
        args += [f"%{keyword}%", f"%{keyword}%"]
    if due_after:
        where.append("substr(due_date,1,10) >= ?"); args.append(due_after)
    if due_before:
        where.append("substr(due_date,1,10) <= ?"); args.append(due_before)
    if posted_after:
        where.append("substr(posted_date,1,10) >= ?"); args.append(posted_after)
    sql = (f"SELECT * FROM solicitations WHERE {' AND '.join(where)} "
           f"ORDER BY due_date LIMIT ?")
    rows = conn.execute(sql, args + [int(limit)]).fetchall()
    return {"status": "ok", "source": source, "count": len(rows),
            "results": [_row_record(r, cols) for r in rows]}


def get_opportunity(solicitation_id, account="anonymous"):
    meter(account, "get_opportunity")
    conn = _conn()
    cols = [c[1] for c in conn.execute("PRAGMA table_info(solicitations)")]
    row = conn.execute("SELECT * FROM solicitations WHERE solicitation_id = ?",
                       (solicitation_id,)).fetchone()
    if not row:
        return {"status": "not_found", "solicitation_id": solicitation_id}
    rec = _row_record(row, cols)
    if not _healthy(conn, rec["source"]):
        return _unavailable(rec["source"], conn)
    return {"status": "ok", "opportunity": rec}


def list_recent_changes(since=None, limit=100, account="anonymous"):
    """THE DIFFERENTIATOR: deadline extensions, new awards, addenda — what changed."""
    meter(account, "list_recent_changes")
    conn = _conn()
    # only surface changes for HEALTHY sources; never internal audit rows.
    healthy_sources = [s for s in [ACTIVE_SOURCE_NAME] if _healthy(conn, s)]
    if not healthy_sources:
        return {"status": "source_temporarily_unavailable", "changes": []}
    qmarks = ",".join("?" * len(healthy_sources))
    where = [f"cl.source IN ({qmarks})", "cl.field != '__REJECTED__'"]
    args = list(healthy_sources)
    if since:
        where.append("cl.changed_at >= ?"); args.append(since)
    sql = (f"SELECT cl.solicitation_id, cl.field, cl.old_value, cl.new_value, "
           f"cl.changed_at, s.title, cl.source FROM change_log cl "
           f"LEFT JOIN solicitations s ON s.solicitation_id = cl.solicitation_id "
           f"AND s.source = cl.source WHERE {' AND '.join(where)} "
           f"ORDER BY cl.changed_at DESC, cl.id DESC LIMIT ?")
    rows = conn.execute(sql, args + [int(limit)]).fetchall()
    label = {"due_date": "deadline_changed", "status": "status_changed",
             "document_links": "documents_changed", "title": "title_changed",
             "agency": "agency_changed", "category": "category_changed",
             "posted_date": "posting_changed"}
    out = []
    for sid, field, old, new, at, title, source in rows:
        ev = {"event": label.get(field, f"{field}_changed"),
              "solicitation_id": sid, "title": title, "field": field,
              "changed_at": at, "source": source}
        if field == "status":
            ev["from"], ev["to"] = old, new
        elif field == "due_date":
            ev["old_due_date"], ev["new_due_date"] = old, new
        elif field == "document_links":
            try:
                o = {d["url"] for d in json.loads(old or "[]")}
                n = {d["url"] for d in json.loads(new or "[]")}
                ev["documents_added"] = len(n - o)
                ev["documents_removed"] = len(o - n)
            except Exception:
                pass
        else:
            ev["old_value"], ev["new_value"] = old, new
        out.append(ev)
    return {"status": "ok", "count": len(out), "changes": out}


TOOLS = {
    "search_opportunities": search_opportunities,
    "get_opportunity": get_opportunity,
    "list_recent_changes": list_recent_changes,
}
