#!/usr/bin/env python3
"""
mcp_server.py — MCP server for the government-procurement feeds (THIN CLIENT).

Speaks the MCP stdio transport: newline-delimited JSON-RPC 2.0 (initialize,
tools/list, tools/call). The three tools call the LIVE Apify Actor synchronously
and return real data — so a fresh clone needs NO local database to work.

Setup:
  export APIFY_TOKEN=<your Apify API token>     # required (runs the Actor)
  export SLED_SOURCE=mississippi                # or: uk_contracts_finder
  python3 mcp_server.py                          # reads JSON-RPC on stdin
Note: each tool call runs the Actor (cold ~15-40s); results are live.
"""
import json
import os
import sys
import urllib.request

PROTOCOL_VERSION = "2024-11-05"

# Which live Apify Actor backs this MCP server (consistent with serve.py's SLED_SOURCE).
SLED_SOURCE = os.environ.get("SLED_SOURCE", "mississippi")
ACTOR_BY_SOURCE = {
    "mississippi": "yTSAmhc6hr4mtVGLe",          # toby_richmond/mississippi-procurement-feed
    "uk_contracts_finder": "ubb1FLxcypwyukPQ9",  # toby_richmond/uk-contracts-finder-feed
}
ACTOR_ID = ACTOR_BY_SOURCE.get(SLED_SOURCE, ACTOR_BY_SOURCE["mississippi"])
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")
SERVER_NAME = f"sled-feed-{SLED_SOURCE}"


def call_actor(tool, args, timeout=300):
    """Run the live Apify Actor synchronously; return its dataset items (real data)."""
    if not APIFY_TOKEN:
        return {"status": "error",
                "detail": "Set APIFY_TOKEN (your Apify API token) to use this MCP server."}
    body = json.dumps({"tool": tool, **args}).encode()
    url = (f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items"
           f"?token={APIFY_TOKEN}")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

TOOL_SCHEMAS = [
    {
        "name": "search_opportunities",
        "description": "Search Mississippi state government solicitations (open-market "
                       "procurement opportunities). Filter by category, keyword, status, "
                       "and posted/due dates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "description": "State code (MVP: MS).", "default": "MS"},
                "category": {"type": "string", "description": "Procurement category substring, e.g. 'INFORMATION TECHNOLOGY'."},
                "keyword": {"type": "string", "description": "Keyword in title/category."},
                "status": {"type": "string", "enum": ["Open", "Closed", "Awarded", "Archived"]},
                "posted_after": {"type": "string", "description": "YYYY-MM-DD."},
                "due_after": {"type": "string", "description": "YYYY-MM-DD."},
                "due_before": {"type": "string", "description": "YYYY-MM-DD."},
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    {
        "name": "get_opportunity",
        "description": "Get one solicitation by its solicitation_id, including all "
                       "document_links (solicitation PDF + attachments).",
        "inputSchema": {
            "type": "object",
            "properties": {"solicitation_id": {"type": "string"}},
            "required": ["solicitation_id"],
        },
    },
    {
        "name": "list_recent_changes",
        "description": "THE DIFFERENTIATOR: what CHANGED — deadline extensions, new "
                       "awards (Open->Awarded), and added addenda/documents — which the "
                       "free state portal does not surface. Optional `since` (ISO-8601).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "since": {"type": "string", "description": "ISO-8601 timestamp; only changes at/after."},
                "limit": {"type": "integer", "default": 100},
            },
        },
    },
]


def handle(req):
    method = req.get("method")
    rid = req.get("id")
    if method == "initialize":
        return _ok(rid, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": "0.1.0"},
        })
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _ok(rid, {"tools": TOOL_SCHEMAS})
    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        args = dict(params.get("arguments") or {})
        if name not in {t["name"] for t in TOOL_SCHEMAS}:
            return _err(rid, -32602, f"unknown tool {name!r}")
        try:
            result = call_actor(name, args)        # live Apify Actor run
        except Exception as e:  # noqa: BLE001
            return _ok(rid, {"content": [{"type": "text", "text": json.dumps(
                {"status": "error", "detail": str(e)})}], "isError": True})
        return _ok(rid, {"content": [{"type": "text",
                   "text": json.dumps(result, indent=2)}], "isError": False})
    return _err(rid, -32601, f"method not found: {method}")


def _ok(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid, code, msg):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}}


def serve_stdio():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


def selftest():
    reqs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "search_opportunities",
                    "arguments": {"status": "Open", "keyword": "information", "limit": 2}}},
    ]
    for r in reqs:
        print(json.dumps(handle(r))[:400])


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        serve_stdio()
