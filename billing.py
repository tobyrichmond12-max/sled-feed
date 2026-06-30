#!/usr/bin/env python3
"""
billing.py — minimal real usage metering for the SLED feed (single-state MVP).

Every billable tool call is recorded to a usage ledger (per account, per tool,
amount). `_platform_charge` is the single integration point where the hosting
platform's meter is actually hit — Apify pay-per-event (`Actor.charge`) or an MCP
marketplace's per-call billing. Kept deliberately small: prove the call is metered
end to end, don't build invoicing for an unproven market.
"""
import os
import sqlite3
from datetime import datetime, timezone

import store

# Minimal, sane pricing for a single-state MVP (USD per call).
PRICING = {
    "search_opportunities": 0.01,
    "get_opportunity": 0.01,
    "list_recent_changes": 0.02,   # the differentiator — priced a touch higher
}
FREE_TIER_CALLS = 100              # first N calls/account free, then metered


def _conn():
    return sqlite3.connect(store.DB_PATH)


# Our own calls (tests, self-checks, the MCP default). Anything NOT in here is
# treated as a REAL EXTERNAL caller. The published surface receives a real
# platform account id (Apify user id / MCP marketplace account) -> classed external.
TEST_ACCOUNTS = {"test-acct", "mcp-client", "paid-demo", "anonymous",
                 "mcp-client-selftest", "self-test"}


def classify_origin(account):
    a = (account or "").lower()
    if a in TEST_ACCOUNTS or a.startswith(("test", "selftest", "self-test", "ci-")):
        return "test"
    return "external"


def init_billing(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS usage(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, account TEXT, tool TEXT,
        units INT, unit_price REAL, amount REAL, billable INT, platform_ref TEXT)""")
    if "origin" not in [r[1] for r in conn.execute("PRAGMA table_info(usage)")]:
        conn.execute("ALTER TABLE usage ADD COLUMN origin TEXT DEFAULT 'test'")
    conn.commit()


def meter(account, tool, units=1):
    """Record a billable event and hit the platform meter. Returns the ledger row."""
    conn = _conn()
    init_billing(conn)
    now = datetime.now(timezone.utc).isoformat()
    price = PRICING.get(tool, 0.0)
    prior = conn.execute("SELECT COUNT(*) FROM usage WHERE account=?", (account,)).fetchone()[0]
    billable = 1 if prior >= FREE_TIER_CALLS else 0
    amount = price * units if billable else 0.0
    origin = classify_origin(account)
    ref = _platform_charge(account, tool, units, billable)
    conn.execute("""INSERT INTO usage(ts,account,tool,units,unit_price,amount,billable,platform_ref,origin)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        (now, account, tool, units, price, amount, billable, ref, origin))
    conn.commit()
    return {"ts": now, "account": account, "tool": tool, "units": units,
            "amount": amount, "billable": bool(billable), "platform_ref": ref,
            "origin": origin}


def usage_report():
    """Phase-6 measurement: distinguish our test traffic from REAL external calls,
    count unique external accounts, per-tool, and specifically whether anyone calls
    list_recent_changes (the change-tracking differentiator signal)."""
    conn = _conn()
    init_billing(conn)
    def q1(sql, a=()):
        return conn.execute(sql, a).fetchone()[0]
    ext_tool = dict(conn.execute(
        "SELECT tool,COUNT(*) FROM usage WHERE origin='external' GROUP BY tool").fetchall())
    test_tool = dict(conn.execute(
        "SELECT tool,COUNT(*) FROM usage WHERE origin='test' GROUP BY tool").fetchall())
    return {
        "impressions": "n/a locally (platform-reported once listing is live)",
        "total_calls": q1("SELECT COUNT(*) FROM usage"),
        "by_origin": {
            "test": q1("SELECT COUNT(*) FROM usage WHERE origin='test'"),
            "external": q1("SELECT COUNT(*) FROM usage WHERE origin='external'"),
        },
        "unique_external_accounts": q1(
            "SELECT COUNT(DISTINCT account) FROM usage WHERE origin='external'"),
        "external_calls_by_tool": ext_tool,
        "test_calls_by_tool": test_tool,
        "differentiator_signal": {
            "external_list_recent_changes_calls": ext_tool.get("list_recent_changes", 0),
        },
        "billable_calls": q1("SELECT COUNT(*) FROM usage WHERE billable=1"),
        "billable_amount": round(q1("SELECT COALESCE(SUM(amount),0) FROM usage"), 4),
    }


def _platform_charge(account, tool, units, billable):
    """Integration point for the hosting platform's meter.

    - Apify Actor (pay-per-event):  `await Actor.charge(event_name=tool, count=units)`
    - MCP marketplace:              per-call metering via the marketplace's billing API
    Here we return a synthetic reference; the real call is wired in the Actor
    wrapper (.actor/) and would be wired to the MCP host at deploy.
    """
    if not billable:
        return "free_tier"
    # e.g. os.environ to detect platform; left as the explicit hook.
    return f"charge::{tool}::{account}"


def usage_summary(account=None):
    conn = _conn()
    init_billing(conn)
    q = "SELECT account,tool,COUNT(*),SUM(units),SUM(amount) FROM usage"
    args = ()
    if account:
        q += " WHERE account=?"
        args = (account,)
    q += " GROUP BY account,tool ORDER BY account,tool"
    rows = conn.execute(q, args).fetchall()
    return [{"account": r[0], "tool": r[1], "calls": r[2], "units": r[3],
             "amount": round(r[4] or 0, 4)} for r in rows]


if __name__ == "__main__":
    import json
    print(json.dumps(usage_summary(), indent=2))
