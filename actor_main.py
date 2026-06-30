#!/usr/bin/env python3
"""
actor_main.py — Apify Actor entrypoint (publish-time surface).

Reuses the SAME service layer as the MCP server (serve.py): same health gate,
same schema, same change feed. Pay-per-event billing is wired via Actor.charge.

Run order per Actor invocation: ensure the local feed is fresh (run the
fetch→normalize→store pipeline if stale), then dispatch the requested tool,
push results to the dataset, and charge the billable event.

NOTE: built & published in Phase 6 (needs the Apify runtime). The MCP server is
the verified primary surface in Phase 5.
"""
import asyncio
import json
import os

# --- Workaround (Apify platform ahead of its SDK): runs triggered via Apify's
# hosted MCP server (mcp.apify.com) are tagged meta.origin='MCP', but no released
# apify SDK includes that enum value yet, so Actor.__aenter__ crashes validating
# the run object. Teach the enum about 'MCP' BEFORE the SDK builds its pydantic
# models. Remove once the apify SDK ships the 'MCP' origin. ---
try:
    import apify_shared.consts as _apc
    _MO = _apc.MetaOrigin
    if "MCP" not in _MO._value2member_map_:
        _m = _MO._member_type_.__new__(_MO, "MCP")
        _m._name_, _m._value_ = "MCP", "MCP"
        _MO._member_map_["MCP"] = _m
        _MO._value2member_map_["MCP"] = _m
        _MO._member_names_.append("MCP")
except Exception:  # noqa: BLE001
    pass

import serve
import store

from sources import SOURCES

# This Actor serves ONE source, chosen by SLED_SOURCE (default mississippi). The
# SAME image runs the MS or UK Actor; env var + per-source DB/KV-store differ.
SLED_SOURCE = os.environ.get("SLED_SOURCE", "mississippi")
SRC = SOURCES[SLED_SOURCE]
store.DB_PATH = SRC.get("db_path", "sled_feed.db")   # store/serve/billing follow this

# Named KV store persists ACROSS runs (the default unnamed store is purged each
# run). We stash the whole SQLite DB here so change-history accumulates run over
# run — which is what makes list_recent_changes work on the stateless platform.
STATE_KVS = SRC.get("kv_store_name", "sled-mississippi-state")
DB_KEY = "database"


def _simulate_change(Actor):
    """TEST HOOK (not in the public input schema): pre-age one stored due_date by
    7 days so a LATER run, ingesting the real value, detects a deadline change.
    Proves cross-run persistence: if the DB didn't persist, there'd be nothing to
    mutate and no change would surface next run."""
    import sqlite3
    from datetime import datetime, timedelta
    c = sqlite3.connect(store.DB_PATH)
    row = c.execute("SELECT source,solicitation_id,due_date FROM solicitations "
                    "WHERE due_date LIKE '20%T%' LIMIT 1").fetchone()
    if not row:
        Actor.log.info("[sim] no datetime record to mutate yet")
        return
    src, sid, due = row
    newdue = (datetime.fromisoformat(due) - timedelta(days=7)).isoformat()
    c.execute("UPDATE solicitations SET due_date=? WHERE source=? AND solicitation_id=?",
              (newdue, src, sid))
    c.commit()
    Actor.log.info(f"[sim] pre-aged stored due_date of {sid}: {due} -> {newdue}; "
                   "a later run ingesting the real value should log a deadline change")


def _ensure_data():
    """Ingest -> MONITOR -> (then serve). On a fresh container this also creates
    the monitor's health tables and sets the source HEALTHY, so the serving health
    gate has a real verdict to read (and will refuse if the monitor flags trouble).
    Fetch is source-specific: a source module may expose fetch() (UK OCDS paging);
    otherwise the shared cached fetch_records() is used (MS DataTables)."""
    from scraper import normalize
    import monitor
    mod = SRC["module"]
    if hasattr(mod, "fetch"):
        records = mod.fetch()                    # e.g. UK OCDS cursor pagination
    else:
        from fetcher import fetch_records
        records = fetch_records(SRC)             # MS cached DataTables POST
    mapped, _new, _unk = normalize(SRC, records)
    conn = store.init_db(store.DB_PATH)
    store.upsert(conn, mapped)
    mconn = monitor.init_monitor(store.DB_PATH)  # creates source_health etc.
    monitor.run(SRC, raw_records=records, conn=mconn)   # sets health verdict


async def main():
    from apify import Actor                      # provided by the Apify base image
    async with Actor:
        inp = await Actor.get_input() or {}
        tool = inp.get("tool", "search_opportunities")
        account = os.environ.get("APIFY_USER_ID", "apify-user")

        # 1) LOAD persisted DB (prior history) from the named KV store
        kvs = await Actor.open_key_value_store(name=STATE_KVS)
        prior = await kvs.get_value(DB_KEY)
        if prior:
            with open(store.DB_PATH, "wb") as f:
                f.write(prior)
            Actor.log.info(f"loaded persisted DB ({len(prior)} bytes) from KV '{STATE_KVS}'")
        else:
            Actor.log.info(f"no persisted DB in KV '{STATE_KVS}' yet — starting fresh")

        # 2) ingest current bids -> upsert+change-log diff vs persisted -> monitor
        _ensure_data()

        # optional cross-run verification hook (mutates AFTER ingest, persists below)
        if inp.get("_simulate_change"):
            _simulate_change(Actor)

        fn = serve.TOOLS.get(tool)
        if not fn:
            await Actor.fail(status_message=f"unknown tool {tool!r}")
            return
        # Pass ONLY the args this tool accepts. The input schema injects defaults
        # (e.g. status='Open') that don't apply to every tool — filter by signature
        # so list_recent_changes/get_opportunity don't get an unexpected 'status'.
        import inspect
        valid = set(inspect.signature(fn).parameters)
        kwargs = {k: v for k, v in inp.items()
                  if k in valid and k != "tool" and v not in (None, "")}
        result = fn(account=account, **kwargs)

        # Billing: FREE during early access (no monetization configured). Default
        # is free-mode -> we DON'T call charge at all, so a run can't error on an
        # unconfigured event. When monetization is enabled later, set SLED_FREE_MODE=0
        # and these per-tool events bill (names must match the console config).
        if os.environ.get("SLED_FREE_MODE", "1") == "1":
            Actor.log.info(f"[free early-access] not charging for event {tool!r}")
        else:
            try:
                await Actor.charge(event_name=tool)
            except Exception as e:                # noqa: BLE001
                Actor.log.warning(f"charge skipped for {tool!r}: {e}")

        items = (result.get("results") or result.get("changes")
                 or [result.get("opportunity")] if result.get("opportunity") else [result])
        await Actor.push_data([x for x in items if x])
        await Actor.set_value("OUTPUT", result)
        Actor.log.info(f"{tool}: {json.dumps(result)[:200]}")

        # 3) SAVE the updated DB back to the named KV store for the next run.
        # store uses WAL journal mode, so committed rows can still live in the
        # -wal sidecar; `VACUUM INTO` writes a COMPLETE, self-contained snapshot
        # (all data merged) — saving the raw .db alone would lose WAL contents.
        import sqlite3
        snap = "/tmp/sled_snapshot.db"
        if os.path.exists(snap):
            os.remove(snap)
        cx = sqlite3.connect(store.DB_PATH)
        cx.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        cx.execute(f"VACUUM INTO '{snap}'")
        cx.close()
        with open(snap, "rb") as f:
            db_bytes = f.read()
        await kvs.set_value(DB_KEY, db_bytes, content_type="application/octet-stream")
        Actor.log.info(f"persisted DB ({len(db_bytes)} bytes) to KV '{STATE_KVS}'")


if __name__ == "__main__":
    asyncio.run(main())
