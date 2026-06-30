# sled-feed — Government procurement feeds with change tracking (MCP)

Search live **US (Mississippi)** and **UK (Contracts Finder)** government bids, RFPs and
tenders — and get the one thing the official portals won't push you: **what CHANGED.**
Deadline extensions, new awards, and posted addenda, exposed as **Model Context Protocol
(MCP) tools** so an AI agent can query procurement data directly.

- 🇺🇸 **Mississippi** state government solicitations (official DFA Contract Bid Search)
- 🇬🇧 **UK Contracts Finder** tenders (official Cabinet Office OCDS API, Open Government Licence v3.0)

Both feeds expose the **same three MCP tools**. The standalone server (`mcp_server.py`) is a
thin client that runs the live [Apify](https://apify.com) Actors on demand, so **a fresh
clone returns real data with no local database to seed.**

## Tools

| Tool | What it does |
|---|---|
| `search_opportunities` | Filter live tenders/bids by category, keyword, status, posted/due dates. |
| `get_opportunity` | Full record by id, including all document links + the official notice URL. |
| `list_recent_changes` | **The differentiator** — deadline changes, new awards (Open → Awarded), added documents over time. |

## Quickstart (standalone MCP server, stdio)

The server is **pure Python standard library** — no `pip install` required. You only need
an Apify API token (free tier works); each call runs the live Actor on your own account.

```bash
git clone https://github.com/tobyrichmond12-max/sled-feed.git
cd sled-feed
export APIFY_TOKEN=<your Apify API token>      # required — get one at apify.com (free)
export SLED_SOURCE=mississippi                  # or: uk_contracts_finder
python3 mcp_server.py                           # speaks MCP over stdio (JSON-RPC 2.0)

# sanity check without a client:
python3 mcp_server.py --selftest
```

### MCP client config (Claude Desktop / VS Code / Cursor)

```json
{
  "mcpServers": {
    "sled-feed-mississippi": {
      "command": "python3",
      "args": ["/absolute/path/to/sled-feed/mcp_server.py"],
      "env": { "APIFY_TOKEN": "YOUR_APIFY_TOKEN", "SLED_SOURCE": "mississippi" }
    },
    "sled-feed-uk": {
      "command": "python3",
      "args": ["/absolute/path/to/sled-feed/mcp_server.py"],
      "env": { "APIFY_TOKEN": "YOUR_APIFY_TOKEN", "SLED_SOURCE": "uk_contracts_finder" }
    }
  }
}
```

### No-install alternative: Apify hosted MCP

Both feeds are also callable through Apify's hosted MCP server — no clone, no local process:

```json
{
  "mcpServers": {
    "apify-gov-feeds": {
      "url": "https://mcp.apify.com/?tools=toby_richmond/mississippi-procurement-feed,toby_richmond/uk-contracts-finder-feed",
      "headers": { "Authorization": "Bearer YOUR_APIFY_TOKEN" }
    }
  }
}
```

## Example usage

```jsonc
// search open IT bids
{ "name": "search_opportunities",
  "arguments": { "status": "Open", "keyword": "information", "limit": 5 } }

// the change feed (the differentiator)
{ "name": "list_recent_changes",
  "arguments": { "since": "2026-06-01T00:00:00" } }
```

Example record (Mississippi):

```json
{
  "solicitation_id": "1601-26-R-RFIN-00066",
  "title": "SPIRIT Management Information System ...",
  "agency": "Mississippi Department of Health",
  "category": "INFORMATION TECHNOLOGY (IT)",
  "status": "Open",
  "due_date": "2026-06-30T15:00:00-05:00",
  "due_timezone": "America/Chicago",
  "document_links": [{ "label": "Solicitation PDF", "url": "https://.../FORM.PDF" }],
  "source_url": "https://www.ms.gov/dfa/contract_bid_search/Bid/Details/45668"
}
```

Example change event (`list_recent_changes`):

```json
{ "event": "deadline_changed", "solicitation_id": "1601-26-R-RFIN-00066",
  "old_due_date": "2026-06-30T15:00:00-05:00", "new_due_date": "2026-07-07T15:00:00-05:00" }
```

## Data, schema & privacy

Per solicitation: `solicitation_id`, `title`, `agency` (buying **organisation** only),
`category`, `bid_type`, `posted_date` / `due_date` (ISO-8601 with explicit timezone and
closing time), `status` (Open / Closed / Awarded / Archived), `document_links`,
`source` / `source_url`. The UK feed also carries `estimated_value` + `value_currency`.

**No personal data.** Buyer contact names/emails/phones in the source are stripped at
ingestion and re-checked at storage; only solicitation data and the buying organisation
name are served. A built-in monitor watches for upstream breakage (renamed fields,
response-shape changes, record-count crashes, new status values, or PII drifting toward
output) and returns "temporarily unavailable" rather than serving stale or wrong data.

## How it works

```
MCP client ──stdio──> mcp_server.py ──HTTPS──> Apify Actor (run-sync) ──> official gov API
                       (thin client)            (ingest → diff → change-log → serve)
```

The Actors persist a SQLite snapshot in a named Apify key-value store between runs, so the
change history (`list_recent_changes`) accumulates run over run. Source code for the
pipeline, monitor, and storage layer is all in this repo.

## License

Code: **MIT** (see [LICENSE](LICENSE)). UK Contracts Finder data is provided under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)
(commercial reuse permitted). Mississippi data is public-record government information.
