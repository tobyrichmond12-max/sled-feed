# MCP Registry / Directory Submissions — government procurement feeds

**ONE listing for both feeds.** A single public repo serves US (Mississippi) and UK
(Contracts Finder) procurement data through the SAME MCP server, switched by the
`SLED_SOURCE` env var. Submit it once — do not file separate MS and UK entries.

- **Repo (live, public):** https://github.com/tobyrichmond12-max/sled-feed
- **Standalone MCP server:** `mcp_server.py` — a thin client that runs the live Apify
  Actors on demand, so a fresh clone returns real data with no local DB to seed.
- **Tools (3, both feeds):** `search_opportunities`, `get_opportunity`, `list_recent_changes`
- **Backing Apify Actors:**
  - Mississippi — `toby_richmond/mississippi-procurement-feed` (id `yTSAmhc6hr4mtVGLe`)
  - UK — `toby_richmond/uk-contracts-finder-feed` (id `ubb1FLxcypwyukPQ9`)
- **License:** MIT (code). UK data under Open Government Licence v3.0.
- **Auth / token model:** each user supplies their OWN Apify API token via
  `APIFY_TOKEN`. Every config below uses a `YOUR_APIFY_TOKEN` placeholder — no secrets
  are committed or shared.

---

## Install / config (paste into submissions)

**Standalone MCP server (stdio) — pure Python stdlib, no `pip install`:**
```json
{ "mcpServers": { "sled-feed-mississippi": {
    "command": "python3",
    "args": ["/path/to/sled-feed/mcp_server.py"],
    "env": { "APIFY_TOKEN": "YOUR_APIFY_TOKEN", "SLED_SOURCE": "mississippi" } } } }
```
Switch the feed with `SLED_SOURCE`: `mississippi` or `uk_contracts_finder`. To run both
at once, add a second entry (e.g. `sled-feed-uk`) with `SLED_SOURCE=uk_contracts_finder`.

**No-install alternative — Apify hosted MCP (both feeds, remote):**
```json
{ "mcpServers": { "apify-gov-feeds": {
    "url": "https://mcp.apify.com/?tools=toby_richmond/mississippi-procurement-feed,toby_richmond/uk-contracts-finder-feed",
    "headers": { "Authorization": "Bearer YOUR_APIFY_TOKEN" } } } }
```
Apify maps `/` → `--` in tool names: `toby_richmond--mississippi-procurement-feed`,
`toby_richmond--uk-contracts-finder-feed`. Each is ONE tool taking the Actor's input;
the operation is the `tool` argument value (e.g. `{"tool":"search_opportunities", ...}`).

---

## The four registries (current, 2026) + how each takes this listing

| Registry | URL | How to submit | Auth |
|---|---|---|---|
| **Glama** | https://glama.ai/mcp/servers | Auto-crawls public GitHub MCP repos; sign in and add/claim the repo to expedite. Displays the README, license (MIT), a quality/maintenance grade, last-updated, stars, tags. | GitHub |
| **PulseMCP** | https://www.pulsemcp.com/submit | Direct form takes a URL (paste the repo). They also ingest the Official MCP Registry, but the form is the fast path. | none |
| **mcp.so** | https://mcp.so/submit | Submit form / GitHub issue. Highest-SEO of the four. See the ready-to-paste block below. | GitHub |
| **Smithery** | https://smithery.ai/new | **List-only** for this repo: connect the GitHub repo, no hosted deploy. (No `smithery.yaml` — hosting was deliberately not set up.) | GitHub |

---

## Ready-to-paste submission content (ONE listing)

**Server name:** `government-procurement-feeds`

**One-sentence description:**
> Search live US (Mississippi) & UK government bids/tenders and track what changed —
> deadline moves, new awards, added documents — as MCP tools.

**Longer description (for fields that allow it):**
> A Model Context Protocol server exposing US and UK government procurement data through
> one server (switch feeds with `SLED_SOURCE`). Tools: `search_opportunities` (filter live
> tenders/bids by category, keyword, status, dates), `get_opportunity` (full record +
> document links by id), and `list_recent_changes` (the differentiator — deadline changes,
> new awards, added documents over time). Clean JSON, no PII (buying organisation only).
> UK data under the Open Government Licence v3.0.

**Tools (3):**
- `search_opportunities(state?, category?, keyword?, status?, posted_after?, due_after?, due_before?, limit?) -> { results: [...] }`
- `get_opportunity(solicitation_id) -> { opportunity: {...} }`
- `list_recent_changes(since?, limit?) -> { changes: [ { event, solicitation_id, ... } ] }`

**Example usage:**
```json
// search
{ "name": "search_opportunities", "arguments": { "status": "Open", "keyword": "information", "limit": 5 } }
// change feed (the differentiator)
{ "name": "list_recent_changes", "arguments": { "since": "2026-06-01T00:00:00" } }
```

**Categories / tags:** government, procurement, tenders, bids, RFP, govtech, open-data, OCDS.

**server.json:** present in the repo (`OWNER` set to `tobyrichmond12-max`); used by the
Official Registry path, which is intentionally skipped for now.

---

## mcp.so — exact submission block (highest priority)

- **Server name:** `government-procurement-feeds`
- **One-sentence description:** Search live US & UK government bids/tenders and track what changed — deadline moves, new awards, added documents — as MCP tools.
- **Tool count:** 3
- **Transport:** stdio (also callable as a remote server via Apify hosted MCP)
- **GitHub repo URL:** https://github.com/tobyrichmond12-max/sled-feed
- **Homepage URL:** https://apify.com/toby_richmond/mississippi-procurement-feed
- **Auth config snippet (this server needs an Apify token):**
```json
{ "mcpServers": { "sled-feed-mississippi": {
    "command": "python3",
    "args": ["/path/to/sled-feed/mcp_server.py"],
    "env": { "APIFY_TOKEN": "YOUR_APIFY_TOKEN", "SLED_SOURCE": "mississippi" } } } }
```
