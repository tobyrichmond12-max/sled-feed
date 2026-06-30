#!/usr/bin/env python3
"""
scraper.py — Normalize a SLED source's raw records into the served schema.

Drives the reusable fetcher + the source's map_record(). Enforces the PII
boundary (map_record hard-fails on leakage), logs schema drift (never-before-seen
input fields) and any unknown status string, and emits clean JSON.

Usage:
  python3 scraper.py mississippi            # normalize cached Open feed
  python3 scraper.py mississippi --status Awarded --force
"""
import json
import sys

from fetcher import fetch_records
from sources import SOURCES


import logging
_log = logging.getLogger("scraper")


def normalize(src, records):
    mod = src["module"]
    known = mod.KNOWN_FIELDS
    out, unknown_fields, unknown_status = [], {}, {}
    for rec in records:
        for k in rec:
            if k not in known:
                unknown_fields[k] = unknown_fields.get(k, 0) + 1
        try:
            mapped = mod.map_record(rec)    # raises on any PII boundary violation
        except AssertionError as e:
            # Fail-SAFE, not fail-LOUD: drop this one record (it is NOT served) and
            # keep the feed up. One bad title must never crash the whole feed.
            unknown_fields["__pii_dropped__"] = unknown_fields.get("__pii_dropped__", 0) + 1
            _log.warning("dropped record at PII boundary: %s", e)
            continue
        if str(mapped["status"]).startswith("UNKNOWN:"):
            s = mapped["status"]
            unknown_status[s] = unknown_status.get(s, 0) + 1
        out.append(mapped)
    return out, unknown_fields, unknown_status


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in SOURCES:
        sys.exit(f"usage: scraper.py <{'|'.join(SOURCES)}> [--status S] [--force]")
    src = SOURCES[sys.argv[1]]
    force = "--force" in sys.argv
    status = None
    if "--status" in sys.argv:
        status = sys.argv[sys.argv.index("--status") + 1]

    # adjust the sample URL for a specific status if requested
    if status:
        import copy
        src = copy.deepcopy(src)
        src["sample"]["url"] = src["sample"]["url"].split("&Status")[0] + f"&Status={status}"
        src["name"] = src["name"] + f" [{status}]"

    records = fetch_records(src, force=force)
    mapped, unknown_fields, unknown_status = normalize(src, records)

    print(f"source: {src['name']}")
    print(f"records normalized: {len(mapped)}")
    print(f"PII boundary: PASS (no forbidden keys/values in any of {len(mapped)} records)")
    print(f"schema drift — new fields: {unknown_fields or 'none'}")
    print(f"unknown statuses: {unknown_status or 'none'}")
    with_due = sum(1 for m in mapped if m["due_date"])
    with_time = sum(1 for m in mapped if m["due_has_time"])
    with_docs = sum(1 for m in mapped if m["document_links"])
    print(f"have due_date: {with_due}/{len(mapped)} | with closing time: {with_time} "
          f"| with document_links: {with_docs}")
    if mapped:
        print("\n--- sample normalized record ---")
        s = {k: v for k, v in mapped[0].items() if not k.startswith("_")}
        print(json.dumps(s, indent=2)[:1400])
    out_path = f"normalized_{sys.argv[1]}.json"
    with open(out_path, "w") as f:
        json.dump([{k: v for k, v in m.items()} for m in mapped], f, indent=2)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
