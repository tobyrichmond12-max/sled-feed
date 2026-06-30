#!/usr/bin/env python3
"""
monitor.py — Source-agnostic self-healing maintenance monitor for the SLED fleet.

Driven entirely by a source's descriptor + its machine-readable CONTRACT, so
adding a source = adding a descriptor, never editing this file.

Two failure modes, handled differently:
  * TRANSIENT (timeout/500/blip): retry w/ backoff; only ESCALATE after N
    CONSECUTIVE failed runs. A single blip self-heals silently.
  * STRUCTURAL (field renamed, shape changed, count cratered, new status, PII
    reappears): detect fast -> STOP serving the source -> emit a loud structured
    alert. Auto-fix NEVER runs unsupervised; re-derivation only STAGES a proposal
    for a human to review. Serving subtly-wrong data is worse than visible downtime.

Severity -> health:
  LOG            : informational; source stays HEALTHY.
  ESCALATE       : source marked unhealthy; Phase-5 serving must stop THIS source.
  STOP_EVERYTHING: fleet-wide halt (PII tripwire / clearance flip).
"""
import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timezone

from store import DB_PATH

log = logging.getLogger("monitor")
ALERTS_FILE = "alerts.jsonl"

MAX_CONSECUTIVE_TRANSIENT = 3   # escalate only if a transient persists this long
FETCH_RETRIES = 3               # in-run retries w/ backoff before counting a failure
BASELINE_WINDOW = 10

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[-.\s])?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)")
SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
CONTACT_NAME_RE = re.compile(r"(name|email|e-mail|phone|fax|mobile|cell|ssn|contact)", re.I)


# --------------------------------------------------------------------------- DB
def init_monitor(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE IF NOT EXISTS source_health(
        source TEXT PRIMARY KEY, state TEXT, reason TEXT, updated_at TEXT,
        latched INT DEFAULT 0)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS monitor_state(
        source TEXT PRIMARY KEY, consecutive_failures INT, baseline TEXT,
        last_clearance TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS alerts(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, source TEXT, severity TEXT,
        check_name TEXT, fields TEXT, old_value TEXT, new_value TEXT,
        record_count INT, baseline REAL, detail TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS staged_rederivations(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, source TEXT,
        served_field TEXT, missing_raw TEXT, proposed_raw TEXT, sample TEXT,
        needs_review INT DEFAULT 1, applied INT DEFAULT 0)""")
    # migration: add latched to a pre-existing source_health table
    if "latched" not in [r[1] for r in conn.execute("PRAGMA table_info(source_health)")]:
        conn.execute("ALTER TABLE source_health ADD COLUMN latched INT DEFAULT 0")
    conn.commit()
    return conn


def _state(conn, source):
    row = conn.execute("SELECT consecutive_failures,baseline FROM monitor_state WHERE source=?",
                       (source,)).fetchone()
    if not row:
        return 0, []
    return row[0], json.loads(row[1] or "[]")


def _save_state(conn, source, cf, baseline, now):
    conn.execute("""INSERT INTO monitor_state(source,consecutive_failures,baseline,last_clearance)
        VALUES(?,?,?,?) ON CONFLICT(source) DO UPDATE SET
        consecutive_failures=excluded.consecutive_failures, baseline=excluded.baseline""",
        (source, cf, json.dumps(baseline[-BASELINE_WINDOW:]), now))
    conn.commit()


_RANK = {"UNKNOWN": 0, "HEALTHY": 0, "ESCALATE": 1, "STOP_EVERYTHING": 2}


def set_health(conn, source, state, reason, now, latched=0):
    conn.execute("""INSERT INTO source_health(source,state,reason,updated_at,latched)
        VALUES(?,?,?,?,?) ON CONFLICT(source) DO UPDATE SET
        state=excluded.state, reason=excluded.reason, updated_at=excluded.updated_at,
        latched=excluded.latched""", (source, state, reason, now, latched))
    conn.commit()


def health_of(conn, source):
    try:
        r = conn.execute("SELECT state,reason,latched FROM source_health WHERE source=?",
                         (source,)).fetchone()
    except sqlite3.OperationalError:
        return ("UNKNOWN", "monitor not initialized", 0)  # defensive: never crash serving
    return (r[0], r[1], r[2]) if r else ("UNKNOWN", "", 0)


def clear_health(conn, source, now=None):
    """Human-in-the-loop ack: clear a latched unhealthy state back to HEALTHY."""
    now = now or datetime.now(timezone.utc).isoformat()
    set_health(conn, source, "HEALTHY", "cleared by human review", now, latched=0)
    conn.execute("UPDATE monitor_state SET consecutive_failures=0 WHERE source=?", (source,))
    conn.commit()


def emit(conn, alert):
    conn.execute("""INSERT INTO alerts(ts,source,severity,check_name,fields,old_value,
        new_value,record_count,baseline,detail) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (alert["ts"], alert["source"], alert["severity"], alert["check"],
         json.dumps(alert.get("fields")), _s(alert.get("old")), _s(alert.get("new")),
         alert.get("record_count"), alert.get("baseline"), alert.get("detail")))
    conn.commit()
    with open(ALERTS_FILE, "a") as f:
        f.write(json.dumps(alert) + "\n")


def _s(v):
    return v if v is None or isinstance(v, str) else json.dumps(v)


# ---------------------------------------------------------------- shape helpers
def _shape_ok(shape, value, status_enum):
    if value is None:
        return True
    v = value if isinstance(value, str) else str(value)
    if shape == "epoch":
        return bool(re.search(r"/Date\(-?\d+\)/", v))
    if shape == "enum":
        return v in status_enum
    if shape == "url":
        return v.startswith("http") or v == ""
    if shape in ("text", "ident"):
        return isinstance(value, (str, int, float))
    return True


# ------------------------------------------------------------- structural checks
def check_structural(src, records):
    """Return list of alert dicts (no I/O). Pure detection from a record batch."""
    mod = src["module"]
    C = mod.CONTRACT
    known = mod.KNOWN_FIELDS
    name = src["name"]
    now = datetime.now(timezone.utc).isoformat()
    alerts = []

    def A(sev, check, **kw):
        alerts.append({"ts": now, "source": name, "severity": sev, "check": check, **kw})

    all_keys = set()
    for r in records:
        all_keys.update(r.keys())
    new_fields = all_keys - set(known)

    # --- LOAD-BEARING presence + shape ---
    for served, spec in C["load_bearing"].items():
        for rf in spec["raw"]:
            present = sum(1 for r in records if rf in r)
            frac = present / len(records) if records else 0
            if frac == 0:
                A("ESCALATE", "load_bearing_field_missing", fields=[rf],
                  old=rf, new=None,
                  detail=f"Load-bearing raw field '{rf}' (-> served '{served}') absent "
                         f"from all {len(records)} records: renamed or removed upstream.")
            else:
                bad = sum(1 for r in records
                          if rf in r and not _shape_ok(spec["shape"], r.get(rf), C["status_enum"]))
                if bad and bad / present > 0.2:
                    sample = next((r.get(rf) for r in records if rf in r), None)
                    A("ESCALATE", "load_bearing_shape_change", fields=[rf],
                      old=f"shape={spec['shape']}", new=f"sample={str(sample)[:40]!r}",
                      detail=f"Field '{rf}' (-> '{served}') failed expected shape "
                             f"'{spec['shape']}' on {bad}/{present} records.")

    # --- STATUS enum ---
    sf = C["status_raw_field"]
    if any(sf in r for r in records):
        seen = {r.get(sf) for r in records if r.get(sf) is not None}
        unknown = seen - set(C["status_enum"])
        if unknown:
            A("ESCALATE", "status_enum_violation", fields=[sf],
              old=sorted(C["status_enum"]), new=sorted(unknown),
              detail=f"New {sf} value(s) {sorted(unknown)} outside the contract enum; "
                     f"would be served as UNKNOWN to customers.")

    # --- PII TRIPWIRE (highest severity) ---
    pii_known = C["pii_known_fields"]
    served_text = {x.lower() for x in C["served_raw_text_fields"]}
    urlf, idf = C["url_field_names"], C["id_field_names"]
    tripped = {}
    for r in records:
        for field, value in r.items():
            fl = field.lower()
            if fl in pii_known or fl in urlf or fl in idf:
                continue
            is_new = field in new_fields
            # a brand-new field whose NAME is contact-shaped is itself a tripwire
            if is_new and CONTACT_NAME_RE.search(fl):
                tripped.setdefault(field, "contact-named new field")
            if not (fl in served_text or is_new):
                continue
            val = value if isinstance(value, str) else ""
            if val.startswith("http"):
                continue
            kind = ("email" if EMAIL_RE.search(val) else "ssn" if SSN_RE.search(val)
                    else "phone" if PHONE_RE.search(val) else None)
            if kind:
                tripped.setdefault(field, f"{kind}-shaped value")
    for field, why in tripped.items():
        A("STOP_EVERYTHING", "pii_tripwire", fields=[field], old=None, new=why,
          detail=f"Contact-shaped data in field '{field}' ({why}) that flows toward "
                 f"served output. Upstream changed to push PII at the boundary. "
                 f"Value withheld from alert by policy.")

    # --- NEW incidental fields (LOG only) ---
    for nf in sorted(new_fields):
        if nf in tripped:
            continue
        A("LOG", "incidental_new_field", fields=[nf], old=None, new=nf,
          detail=f"New field '{nf}' appeared in source (not in known schema); "
                 f"incidental — logged for awareness.")

    return alerts


def propose_rederivation(conn, src, records, missing_raw, now):
    """STAGE a candidate remapping for HUMAN review. Never auto-applies."""
    mod = src["module"]
    C = mod.CONTRACT
    known = mod.KNOWN_FIELDS
    served = next((s for s, sp in C["load_bearing"].items() if missing_raw in sp["raw"]), None)
    shape = C["load_bearing"].get(served, {}).get("shape", "text")
    all_keys = set().union(*[r.keys() for r in records]) if records else set()
    candidates = [k for k in all_keys if k not in known]
    best, best_score, sample = None, 0, None
    for c in candidates:
        vals = [r.get(c) for r in records if r.get(c) is not None][:20]
        if not vals:
            continue
        score = sum(1 for v in vals if _shape_ok(shape, v, C["status_enum"])) / len(vals)
        if score > best_score:
            best, best_score, sample = c, score, vals[0]
    if best and best_score >= 0.7:
        conn.execute("""INSERT INTO staged_rederivations(ts,source,served_field,
            missing_raw,proposed_raw,sample,needs_review,applied)
            VALUES(?,?,?,?,?,?,1,0)""",
            (now, src["name"], served, missing_raw, best, str(sample)[:80]))
        conn.commit()
        return {"served_field": served, "missing_raw": missing_raw,
                "proposed_raw": best, "confidence": round(best_score, 2),
                "sample": str(sample)[:60]}
    return None


# ------------------------------------------------------------------------- run
def run(src, fetch_fn=None, raw_records=None, clearance_fn=None, persist=True,
        conn=None):
    """Execute one monitor cycle. Returns (health_state, alerts)."""
    mod = src["module"]
    name = src["name"]
    now = datetime.now(timezone.utc).isoformat()
    conn = conn or init_monitor()
    cf, baseline = _state(conn, name)
    produced = []

    # 1) acquire records, with transient retry/backoff
    records = raw_records
    if records is None:
        last_err = None
        for attempt in range(FETCH_RETRIES):
            try:
                records = fetch_fn() if fetch_fn else _default_fetch(src)
                last_err = None
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(0.2 * (attempt + 1))
        if last_err is not None:
            cf += 1
            sev = "ESCALATE" if cf >= MAX_CONSECUTIVE_TRANSIENT else "LOG"
            al = {"ts": now, "source": name, "severity": sev, "check": "transient_fetch",
                  "fields": None, "old": None, "new": f"{cf} consecutive failures",
                  "detail": (f"Fetch failed ({last_err}); attempt {cf}/"
                             f"{MAX_CONSECUTIVE_TRANSIENT}. "
                             + ("PERSISTENT — escalating." if sev == "ESCALATE"
                                else "Transient — will retry next run, no escalation."))}
            if persist:
                emit(conn, al)
                _save_state(conn, name, cf, baseline, now)
                if sev == "ESCALATE":
                    set_health(conn, name, "ESCALATE",
                               f"persistent fetch failure x{cf}", now)
            produced.append(al)
            return (("ESCALATE" if sev == "ESCALATE" else health_of(conn, name)[0]),
                    produced)
    cf = 0  # success resets transient counter

    # 2) record-count checks (against trailing baseline)
    count = len(records)
    avg = sum(baseline) / len(baseline) if baseline else None
    if count < mod.CONTRACT["min_records"]:
        produced.append({"ts": now, "source": name, "severity": "ESCALATE",
                         "check": "record_count_zero", "fields": None,
                         "record_count": count, "baseline": avg, "old": avg, "new": count,
                         "detail": f"Returned {count} records (< min {mod.CONTRACT['min_records']}). "
                                   "Silent-breakage signature — stop serving."})
    elif avg and count < (1 - mod.CONTRACT["count_drop_threshold"]) * avg:
        produced.append({"ts": now, "source": name, "severity": "ESCALATE",
                         "check": "record_count_crater", "fields": None,
                         "record_count": count, "baseline": round(avg, 1),
                         "old": round(avg, 1), "new": count,
                         "detail": f"Record count {count} is >{int(mod.CONTRACT['count_drop_threshold']*100)}% "
                                   f"below trailing avg {avg:.0f}. Likely partial/broken pull."})

    # 3) structural + PII checks
    produced += check_structural(src, records)

    # 4) clearance re-check (periodic)
    if clearance_fn is not None:
        verdict = clearance_fn()
        if verdict != "CLEAR":
            produced.append({"ts": now, "source": name, "severity": "ESCALATE",
                             "check": "clearance_reflip", "fields": None,
                             "old": "CLEAR", "new": verdict,
                             "detail": "clearance_filter flipped to ESCALATE (robots/login/"
                                       "anti-bot changed). Stop serving until re-cleared."})

    # 5) severity rollup -> health, with LATCHING. Structural/PII breaks latch
    # (stay stopped until a human clear_health); transient fetch escalations do
    # NOT latch (they auto-recover when the outage ends).
    sevs = {a["severity"] for a in produced}
    structural = any(a["severity"] == "ESCALATE" and a["check"] != "transient_fetch"
                     for a in produced)
    if "STOP_EVERYTHING" in sevs:
        state, reason, this_latched = "STOP_EVERYTHING", "PII tripwire / fleet-halt", 1
    elif "ESCALATE" in sevs:
        state = "ESCALATE"
        reason = "; ".join(sorted({a["check"] for a in produced if a["severity"] == "ESCALATE"}))
        this_latched = 1 if structural else 0
    else:
        state, reason, this_latched = "HEALTHY", "ok", 0

    prev_state, prev_reason, prev_latched = health_of(conn, name)
    if prev_latched and _RANK[state] <= _RANK[prev_state]:
        # a previously-latched break is NOT auto-downgraded by a calmer run
        state, reason, this_latched = prev_state, prev_reason + " (latched)", 1

    # 6) re-derivation staging for missing load-bearing fields (HUMAN review only)
    staged = []
    if persist:
        for a in produced:
            if a["check"] == "load_bearing_field_missing":
                prop = propose_rederivation(conn, src, records, a["fields"][0], now)
                if prop:
                    staged.append(prop)
                    note = {"ts": now, "source": name, "severity": "LOG",
                            "check": "rederivation_staged", "fields": a["fields"],
                            "old": prop["missing_raw"], "new": prop["proposed_raw"],
                            "detail": f"STAGED for human review (NOT applied): '{prop['missing_raw']}' "
                                      f"may map to '{prop['proposed_raw']}' (conf {prop['confidence']}, "
                                      f"sample {prop['sample']!r}). Source stays STOPPED until approved."}
                    produced.append(note)

    # 7) persist alerts + state + health
    if persist:
        for a in produced:
            emit(conn, a)
        # baseline only advances on a healthy run (don't bake a crater into baseline)
        if state == "HEALTHY":
            baseline = (baseline + [count])[-BASELINE_WINDOW:]
        _save_state(conn, name, cf, baseline, now)
        set_health(conn, name, state, reason, now, latched=this_latched)

    return state, produced


def _default_fetch(src):
    from fetcher import fetch_records
    return fetch_records(src)


def console_summary(state, alerts):
    order = {"STOP_EVERYTHING": 0, "ESCALATE": 1, "LOG": 2}
    print(f"  health -> {state}")
    for a in sorted(alerts, key=lambda x: order.get(x["severity"], 9)):
        print(f"   [{a['severity']:>15}] {a['check']}: {a['detail'][:96]}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from sources import SOURCES
    conn = init_monitor()
    st, al = run(SOURCES["mississippi"], conn=conn)
    print(f"\nMonitor run for Mississippi:")
    console_summary(st, al)
