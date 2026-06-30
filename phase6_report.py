#!/usr/bin/env python3
"""Phase-6 measurement — pointed at the LIVE published Apify Actor.

The published surface is the Apify Actor; real external usage shows up in the
Actor's platform stats (totalRuns / totalUsers / unique users 7-30-90d), NOT in
our local ledger (each Actor run meters into ephemeral per-run storage). So this
reads the live Actor stats and reports growth since a launch baseline.

Honest limitation: Apify does not expose external callers' INPUTS to the Actor
owner (privacy), so per-tool external counts — including external calls to
list_recent_changes specifically — are not observable here. Where we DO see
per-tool (our own calls, or an MCP surface with a persistent DB) we show the
local ledger too.
"""
import json
import os
import subprocess

ACTOR = "toby_richmond/mississippi-procurement-feed"
PUBLIC_URL = "https://apify.com/toby_richmond/mississippi-procurement-feed"
BASELINE_FILE = "phase6_baseline.json"
OWNER = "toby_richmond"


def actor_stats():
    out = subprocess.run(["apify", "actors", "info", ACTOR, "--json"],
                         capture_output=True, text=True, timeout=180).stdout
    d = json.loads(out)
    return d.get("stats", {}) or {}, d.get("isPublic")


def main():
    stats, is_public = actor_stats()
    if not os.path.exists(BASELINE_FILE):
        json.dump({"baseline_stats": stats}, open(BASELINE_FILE, "w"), indent=2)
        base, first = stats, True
    else:
        base = json.load(open(BASELINE_FILE)).get("baseline_stats", {})
        first = False

    def d(k):
        return (stats.get(k, 0) or 0) - (base.get(k, 0) or 0)

    print("=" * 60)
    print("SLED FEED — Mississippi — Phase 6 (LIVE Apify Actor)")
    print("=" * 60)
    print(f"listing: {PUBLIC_URL}   public={is_public}")
    print(f"baseline {'RECORDED now (launch)' if first else 'loaded'}: "
          f"totalRuns={base.get('totalRuns')} totalUsers={base.get('totalUsers')}")
    print("-" * 60)
    print("CURRENT platform stats:")
    for k in ("totalRuns", "totalUsers", "totalUsers7Days", "totalUsers30Days",
              "totalUsers90Days", "actorReviewCount", "bookmarkCount"):
        print(f"  {k:18} = {stats.get(k)}")
    print("-" * 60)
    print("SINCE LAUNCH BASELINE (the real demand signal):")
    print(f"  new runs           = {d('totalRuns')}")
    print(f"  new unique users   = {d('totalUsers')}   "
          f"(owner/our tests are part of the baseline, so this is EXTERNAL)")
    print(f"  unique users / 30d = {stats.get('totalUsers30Days')}")

    # local ledger (our own / MCP-surface calls; per-tool incl. list_recent_changes)
    try:
        from billing import usage_report
        u = usage_report()
        print("-" * 60)
        print("LOCAL ledger (per-tool, where observable — MCP surface / our tests):")
        print(f"  external calls       = {u['by_origin']['external']}")
        print(f"  unique ext accounts  = {u['unique_external_accounts']}")
        print(f"  ext list_recent_changes = "
              f"{u['differentiator_signal']['external_list_recent_changes_calls']}")
    except Exception as e:  # noqa: BLE001
        print("local ledger unavailable:", e)

    print("-" * 60)
    new_users = d("totalUsers")
    if new_users <= 0:
        print("READ: 0 external callers since launch. Per the decision rule, SILENCE")
        print("IS AMBIGUOUS — 'coverage too thin to test', NOT 'concept failed'.")
    else:
        print(f"READ: {new_users} new unique user(s) since launch — real external")
        print("interest. Inspect runs/reviews; if change-tracking is the draw, scale.")
    print("\nNOTE: Apify hides external callers' inputs from the owner, so external")
    print("per-tool counts (incl. list_recent_changes) aren't observable here —")
    print("watch the Actor's Analytics tab in the console for unique-user growth.")


if __name__ == "__main__":
    main()
