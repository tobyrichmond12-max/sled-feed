#!/usr/bin/env python3
"""
fetcher.py — Reusable, polite, cached fetch for the SLED feed fleet.

Politeness (non-negotiable):
  - Honest, identifiable User-Agent (same as the clearance filter).
  - On-disk response cache; refuses to re-hit the origin more than once per
    MIN_POLL_SECONDS (default hourly). One call yields the whole state.
  - Backs off and RAISES on any non-200 (never hammers, never serves garbage).

Given a source descriptor's `sample` spec (session_url, method, url, body,
headers, record_path) it returns the parsed record list, from cache when fresh.
"""
import gzip
import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = ("SLEDFeedBot/0.1 (+https://github.com/sled-feed; "
              "public government procurement aggregator)")
MIN_POLL_SECONDS = 3600          # data changes daily at most; poll hourly max
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")


def _read(resp):
    raw = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def _cache_path(key):
    os.makedirs(CACHE_DIR, exist_ok=True)
    safe = "".join(c if c.isalnum() else "_" for c in key)
    return os.path.join(CACHE_DIR, f"{safe}.json")


def fetch_records(src, length=9999, force=False, full_payload=False):
    """Return record list for a source. Uses cache unless older than the poll
    floor. Raises on any non-200 (caller decides; we never silently degrade)."""
    spec = src["sample"]
    key = src.get("name", spec["url"])
    cpath = _cache_path(key)

    if not force and os.path.exists(cpath):
        age = time.time() - os.path.getmtime(cpath)
        if age < MIN_POLL_SECONDS:
            with open(cpath) as f:
                payload = json.load(f)
            payload["_cache"] = f"hit (age {int(age)}s < {MIN_POLL_SECONDS}s floor)"
            return payload if full_payload else payload["records"]

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    def _open(url, method="GET", body=None, headers=None):
        h = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
        if headers:
            h.update(headers)
        data = urllib.parse.urlencode(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        return opener.open(req, timeout=45)

    # 1) establish session (no login) — sets the cookie the API requires
    if spec.get("session_url"):
        r = _open(spec["session_url"])
        if r.status != 200:
            raise RuntimeError(f"session fetch HTTP {r.status}; backing off")
        time.sleep(1.5)

    # 2) one POST for the whole state
    body = dict(spec.get("body") or {})
    if "iDisplayLength" in body:
        body["iDisplayLength"] = str(length)
    try:
        r = _open(spec["url"], method=spec.get("method", "GET"),
                  body=body or None, headers=spec.get("headers"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"origin returned HTTP {e.code}; backing off, not retrying hard")
    if r.status != 200:
        raise RuntimeError(f"origin returned HTTP {r.status}; backing off")
    text = _read(r)
    data = json.loads(text)
    rp = spec.get("record_path")
    records = (data.get(rp) if rp and isinstance(data, dict) else data) or []

    payload = {"fetched_at": time.time(),
               "fetched_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "total_reported": data.get("iTotalRecords"),
               "count": len(records),
               "records": records}
    tmp = cpath + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f)
    os.replace(tmp, cpath)
    payload["_cache"] = "miss (fetched live)"
    return payload if full_payload else records


if __name__ == "__main__":
    import sys
    from sources import SOURCES
    name = sys.argv[1] if len(sys.argv) > 1 else "mississippi"
    force = "--force" in sys.argv
    p = fetch_records(SOURCES[name], force=force, full_payload=True)
    print(f"{name}: {p['count']} records (total_reported={p['total_reported']}), "
          f"{p['_cache']}")
