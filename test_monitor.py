#!/usr/bin/env python3
"""Phase-4 verification: simulate each failure mode, show structured alerts."""
import copy
import json
import sqlite3

import monitor
from fetcher import fetch_records
from sources import SOURCES

src = SOURCES["mississippi"]
name = src["name"]
conn = monitor.init_monitor()
for t in ("source_health", "monitor_state", "alerts", "staged_rederivations"):
    conn.execute(f"DELETE FROM {t}")
conn.commit()
open("alerts.jsonl", "w").close()

GOOD = fetch_records(src)            # 130 real records (cache)


def hp():
    s, r, latched = monitor.health_of(conn, name)
    return f"health={s} latched={latched} reason={r!r}"


def banner(t):
    print("\n" + "=" * 70 + f"\n{t}\n" + "=" * 70)


def run_recs(recs, **kw):
    return monitor.run(src, raw_records=recs, conn=conn, **kw)


# seed a trailing baseline with a few healthy runs
banner("SEED BASELINE (healthy runs)")
for _ in range(3):
    st, al = run_recs(GOOD)
print(f"after 3 healthy runs: {hp()}; baseline={monitor._state(conn, name)[1]}")

# 1) TRANSIENT, single blip recovers within the run -> no escalation
banner("1) TRANSIENT (single blip, recovers on retry) -> NO escalation")
calls = {"n": 0}
def flaky():
    calls["n"] += 1
    if calls["n"] == 1:
        raise TimeoutError("simulated 500/timeout")
    return GOOD
st, al = monitor.run(src, fetch_fn=flaky, conn=conn)
monitor.console_summary(st, al)
print(f"  attempts used: {calls['n']} (failed once, then recovered) | {hp()}")

# 2) TRANSIENT persistent -> escalates after N consecutive, then auto-recovers
banner("2) TRANSIENT persistent -> ESCALATE after N; then auto-recovers")
def dead():
    raise ConnectionError("origin unreachable")
for i in range(monitor.MAX_CONSECUTIVE_TRANSIENT):
    st, al = monitor.run(src, fetch_fn=dead, conn=conn)
    print(f"  run {i+1}: {al[0]['severity']:>9} — {al[0]['new']}")
print(f"  -> {hp()}")
st, al = monitor.run(src, fetch_fn=lambda: GOOD, conn=conn)
print(f"  recovery run (fetch OK): {hp()}  <- transient auto-recovers (not latched)")

# 3) STRUCTURAL field rename (KEY CASE) -> ESCALATE + stop + staged re-derivation
banner("3) STRUCTURAL: load-bearing field renamed BidStatus->BidState")
monitor.clear_health(conn, name)
renamed = [{("BidState" if k == "BidStatus" else k): v for k, v in r.items()} for r in GOOD]
st, al = run_recs(renamed)
monitor.console_summary(st, al)
print(f"  {hp()}   <- source STOPPED (serving layer must skip it)")
print("\n  >>> STRUCTURED ALERT (load-bearing change):")
key_alert = next(a for a in al if a["check"] == "load_bearing_field_missing")
print(json.dumps(key_alert, indent=2))
print("\n  >>> STAGED RE-DERIVATION (human review required, NOT applied):")
for row in conn.execute("""SELECT served_field,missing_raw,proposed_raw,sample,
        needs_review,applied FROM staged_rederivations"""):
    print(f"     served={row[0]} missing_raw={row[1]} -> proposed_raw={row[2]} "
          f"sample={row[3]!r} needs_review={row[4]} applied={row[5]}")
# prove latching: a healthy run does NOT silently un-stop it
st2, _ = run_recs(GOOD)
print(f"  re-run with healthy data: {hp()}  <- stays ESCALATE (latched; needs human)")
monitor.clear_health(conn, name)
print(f"  after human clear_health(): {hp()}")

# 4) RECORD-COUNT crater
banner("4) RECORD-COUNT crater (5 vs ~130 baseline)")
st, al = run_recs(GOOD[:5])
monitor.console_summary(st, al)
print(f"  {hp()}")
monitor.clear_health(conn, name)

# 5) NEW STATUS value outside enum
banner("5) NEW STATUS value 'Frozen' outside {Open,Closed,Awarded,Archived}")
recs = copy.deepcopy(GOOD)
recs[0]["BidStatus"] = "Frozen"
st, al = run_recs(recs)
monitor.console_summary(st, al)
print(f"  {hp()}")
monitor.clear_health(conn, name)

# 6) PII TRIPWIRE (highest severity) -> STOP_EVERYTHING
banner("6) PII TRIPWIRE: contact data pushed toward served fields")
recs = copy.deepcopy(GOOD)
recs[0]["ProjectContactEmail"] = "jane.doe@agency.ms.gov"          # new contact field+value
recs[1]["BidDescription"] = recs[1]["BidDescription"] + " Questions: bob.smith@agency.ms.gov"
st, al = run_recs(recs)
monitor.console_summary(st, al)
print(f"  {hp()}")
print("\n  >>> STRUCTURED ALERT (PII tripwire):")
pii = [a for a in al if a["check"] == "pii_tripwire"]
print(json.dumps(pii, indent=2))
st2, _ = run_recs(GOOD)
print(f"  re-run with clean data: {hp()}  <- STOP_EVERYTHING latched until human ack")
monitor.clear_health(conn, name)

# 7) INCIDENTAL change -> LOG only, stays HEALTHY
banner("7) INCIDENTAL change (new non-PII field) -> LOG only, HEALTHY")
recs = copy.deepcopy(GOOD)
for r in recs:
    r["BudgetFiscalYear"] = "2026"
st, al = run_recs(recs)
monitor.console_summary(st, al)
print(f"  {hp()}  <- not escalated, not stopped")

banner("ALERT LEDGER (counts by severity/check)")
for row in conn.execute("""SELECT severity,check_name,COUNT(*) FROM alerts
        GROUP BY severity,check_name ORDER BY severity,check_name"""):
    print(f"  {row[0]:>15} | {row[1]:<28} x{row[2]}")
print(f"\nalerts.jsonl lines: {sum(1 for _ in open('alerts.jsonl'))}")
