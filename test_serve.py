#!/usr/bin/env python3
"""Phase-5 verification: tools, live cross-check, change feed, metering, health gate, MCP."""
import json
import re
import sqlite3
import subprocess
import urllib.request

import billing
import monitor
import serve
from store import DB_PATH

NAME = "Mississippi DFA Contract Bid Search"
UA = "SLEDFeedBot/0.1 (+https://github.com/sled-feed; public government procurement aggregator)"
conn = monitor.init_monitor(DB_PATH)
monitor.clear_health(conn, NAME)            # ensure HEALTHY at start
ACC = "test-acct"


def banner(t):
    print("\n" + "=" * 68 + f"\n{t}\n" + "=" * 68)


def live_due_agency(url):
    html = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=40).read().decode("utf-8", "replace")
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    sub = re.search(r"Submission Date\s+(\d{2}/\d{2}/\d{4}(?:\s+\d{1,2}:\d{2}\s*[AP]M)?)", t)
    ag = re.search(r"Agency\s+([A-Z0-9][A-Z0-9 &.,'/()\-]+?)\s+(?:RFx|Description|Buyer|Status|Major|Bid)", t)
    return (sub.group(1) if sub else None), (ag.group(1).strip() if ag else None)


# 1) search_opportunities
banner("1) search_opportunities(status=Open, category='INFORMATION TECHNOLOGY')")
res = serve.search_opportunities(status="Open", category="INFORMATION TECHNOLOGY", limit=3, account=ACC)
print(f"   status={res['status']} count={res['count']}")
for r in res["results"][:2]:
    print(f"   - {r['solicitation_id']} | due {r['due_date']} | {r['title'][:54]}")

# 2) get_opportunity + LIVE cross-check (unmodified, future-due record)
banner("2) get_opportunity + live ms.gov cross-check")
SID = "9210-26-R-RFIN-00007"
g = serve.get_opportunity(SID, account=ACC)
op = g["opportunity"]
print(f"   served : {op['solicitation_id']} | due {op['due_date']} | agency {op['agency']!r} | {len(op['document_links'])} docs")
live_due, live_agency = live_due_agency(op["source_url"])
print(f"   live   : Submission Date {live_due!r} | Agency {live_agency!r}")
# stored due 2026-07-16T14:00 -05:00 should equal live '07/16/2026 2:00 PM'
print(f"   MATCH  : agency={'OK' if (live_agency or '').upper().startswith(op['agency'].upper()[:10]) else 'NO'} ;"
      f" due_time={'OK' if '2:00 PM' in (live_due or '') and 'T14:00' in op['due_date'] else 'CHECK'}")
print(f"   estimated_value served as: {op['estimated_value']!r} ({op['estimated_value_note']})")

# 3) list_recent_changes — THE DIFFERENTIATOR
banner("3) list_recent_changes(since=2020-01-01) — the change feed")
ch = serve.list_recent_changes(since="2020-01-01T00:00:00", account=ACC)
print(f"   status={ch['status']} count={ch['count']}")
for e in ch["changes"]:
    extra = {k: v for k, v in e.items() if k in ("from", "to", "old_due_date", "new_due_date", "documents_added")}
    print(f"   - {e['event']:<18} {e['solicitation_id']:<26} {extra}")

# 4) metering: confirm calls recorded; show a billable charge via the platform hook
banner("4) metering ledger")
print("   usage for test-acct (free tier):", json.dumps(billing.usage_summary(ACC)))
orig = billing.FREE_TIER_CALLS
billing.FREE_TIER_CALLS = 0                    # simulate a paid account to fire the charge hook
ev = billing.meter("paid-demo", "list_recent_changes")
billing.FREE_TIER_CALLS = orig
print(f"   billable call (paid-demo): amount=${ev['amount']} platform_ref={ev['platform_ref']!r} billable={ev['billable']}")

# 5) HEALTH GATE — refuse to serve an unhealthy source
banner("5) health gate: mark unhealthy -> refuse -> clear -> resume")
import datetime
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
monitor.set_health(conn, NAME, "ESCALATE", "simulated structural break", now, latched=1)
print("   marked MS ESCALATE (latched).")
r_un = serve.search_opportunities(status="Open", account=ACC)
g_un = serve.get_opportunity(SID, account=ACC)
c_un = serve.list_recent_changes(account=ACC)
print(f"   search          -> {r_un['status']}")
print(f"   get_opportunity -> {g_un['status']}")
print(f"   recent_changes  -> {c_un['status']}")
monitor.clear_health(conn, NAME)
r_ok = serve.search_opportunities(status="Open", account=ACC)
print(f"   after clear_health(): search -> {r_ok['status']} count={r_ok['count']}")

# 6) MCP protocol over stdio (real JSON-RPC)
banner("6) MCP server over stdio (initialize / tools/list / tools/call)")
reqs = "\n".join(json.dumps(r) for r in [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
     "params": {"name": "list_recent_changes", "arguments": {"since": "2020-01-01T00:00:00", "limit": 2}}},
]) + "\n"
out = subprocess.run(["python3", "mcp_server.py"], input=reqs, capture_output=True, text=True, timeout=60).stdout
for line in out.strip().splitlines():
    m = json.loads(line)
    if m["id"] == 1:
        print(f"   initialize -> serverInfo={m['result']['serverInfo']}")
    elif m["id"] == 2:
        print(f"   tools/list -> {[t['name'] for t in m['result']['tools']]}")
    elif m["id"] == 3:
        payload = json.loads(m["result"]["content"][0]["text"])
        print(f"   tools/call list_recent_changes -> status={payload['status']} count={payload['count']}")
print("\nPhase-5 verification complete.")
