# MCP Registry / Directory Submissions — government procurement feeds

Two feeds, each exposing the same MCP tools: `search_opportunities`,
`get_opportunity`, `list_recent_changes`.
- **Mississippi:** Apify Actor `toby_richmond/mississippi-procurement-feed` (id `yTSAmhc6hr4mtVGLe`)
- **UK:** Apify Actor `toby_richmond/uk-contracts-finder-feed` (id `ubb1FLxcypwyukPQ9`)

## ⚠️ Two honest prerequisites before submitting
1. **Most directories index a PUBLIC GitHub repo.** The code is a local git repo only
   (`/home/thoth/sled-feed`). You'll need to push it to a public GitHub repo first
   (e.g. `github.com/<you>/sled-feed`) — that's step 1 of the checklist.
2. **The standalone MCP server (`mcp_server.py`) reads a local SQLite DB**, which is empty
   on a fresh clone (the data lives in the Apify Actors' KV stores). So a third party who
   installs the raw server gets no data until the pipeline runs. **Two clean options:**
   - **(Recommended, zero new infra) List the MCP path via Apify** — any Apify Actor is
     usable as an MCP tool through Apify's hosted MCP server (`mcp.apify.com` /
     `apify/actors-mcp-server`). Agent-builders already on Apify can call our feeds today.
   - **(Small follow-up) Make `mcp_server.py` a thin client** that calls the live Apify
     Actor's API instead of a local DB — then a standalone install "just works" and is worth
     listing on the GitHub-crawled directories. ~30 lines; say the word and I'll build it.

---

## Apify MCP — verified addressing (use this in submissions & posts)
Agent-builders already on Apify can call both feeds today, no install:
- **Server URL:** `https://mcp.apify.com`  · **Auth:** `Authorization: Bearer <APIFY_TOKEN>` (or OAuth in-client)
- **Preload the Actor(s)** via the `tools` query param (comma-separate for both):
  `https://mcp.apify.com/?tools=toby_richmond/mississippi-procurement-feed,toby_richmond/uk-contracts-finder-feed`
- **Tool names (Apify maps `/` → `--`):** `toby_richmond--mississippi-procurement-feed`,
  `toby_richmond--uk-contracts-finder-feed`. Each is ONE tool taking the Actor's input;
  the three operations are the `tool` argument value.
- **Call example (arguments):** `{ "tool": "search_opportunities", "status": "Open", "limit": 5 }`
  (or `{"tool":"list_recent_changes","since":"2026-06-01T00:00:00"}`).

Client config (e.g. Claude Desktop / VS Code):
```json
{ "mcpServers": { "apify-gov-feeds": {
    "url": "https://mcp.apify.com/?tools=toby_richmond/mississippi-procurement-feed,toby_richmond/uk-contracts-finder-feed",
    "headers": { "Authorization": "Bearer YOUR_APIFY_TOKEN" } } } }
```

## The registries that matter (current, 2026) + what each needs

| Registry | URL | How to submit | Needs |
|---|---|---|---|
| **Apify MCP (primary)** | https://mcp.apify.com · `apify/actors-mcp-server` | **VERIFIED working** — both Actors are discoverable + callable as MCP tools (runs succeed, origin=MCP, live data). See exact config below. | Nothing new |
| **Official MCP Registry** | https://registry.modelcontextprotocol.io · repo: github.com/modelcontextprotocol/registry | `server.json` + `mcp-publisher` CLI; auth via **GitHub OAuth** for namespace `io.github.<you>/...`; server must be reachable (PyPI/npm package or remote URL). | Public repo + GitHub auth (+ PyPI or remote) |
| **Glama** | https://glama.ai/mcp/servers | Auto-crawls public GitHub MCP repos; you can claim/submit your repo. | Public repo |
| **PulseMCP** | https://www.pulsemcp.com (submit form) | Submit server (name, repo, description, tools). | Public repo / URL |
| **Smithery** | https://smithery.ai/new | Connect the GitHub repo; optionally add `smithery.yaml` for hosted runs. | Public repo (+ smithery.yaml for hosting) |
| **mcp.so** | https://mcp.so/submit | Submit form (name, repo, description). | Public repo / URL |
| **awesome-mcp-servers** | https://github.com/punkpeye/awesome-mcp-servers | Open a PR adding your entry to the list. | Public repo + a PR |

---

## Ready-to-paste submission content

**Server name (Mississippi):** `mississippi-government-bids`
**Server name (UK):** `uk-government-tenders`
*(Official registry namespace, set `<you>`: `io.github.<you>/mississippi-government-bids` and `io.github.<you>/uk-government-tenders`.)*

**One-liner (MS):** Search Mississippi government bids/RFPs and track what changed — deadline changes, new awards, addenda — as MCP tools.
**One-liner (UK):** Search UK Contracts Finder tenders and track what changed — deadline changes, new awards — as MCP tools (OGL v3.0 data).

**Description (both, adapt state/country):**
> A Model Context Protocol server exposing government procurement data. Tools:
> `search_opportunities` (filter live tenders/bids by category, keyword, status, dates),
> `get_opportunity` (full record + document links by id), and `list_recent_changes`
> (the differentiator — deadline changes, new awards, added documents over time).
> Clean JSON, no PII (buyer organisation only). UK data under the Open Government Licence v3.0.

**Tool list (for the registry's tools field):**
- `search_opportunities(state?, category?, keyword?, status?, posted_after?, due_after?, due_before?, limit?) -> { results: [...] }`
- `get_opportunity(solicitation_id) -> { opportunity: {...} }`
- `list_recent_changes(since?, limit?) -> { changes: [ { event, solicitation_id, ... } ] }`

**Example usage (paste into "example" fields):**
```json
// search
{ "name": "search_opportunities", "arguments": { "status": "Open", "keyword": "facilities", "limit": 5 } }
// change feed (the differentiator)
{ "name": "list_recent_changes", "arguments": { "since": "2026-06-01T00:00:00" } }
```

**Install / endpoint (after public repo + thin-client follow-up, or via Apify MCP):**
- Via Apify MCP: add Actor `toby_richmond/mississippi-procurement-feed` (or `uk-contracts-finder-feed`) through `apify/actors-mcp-server`.
- Via repo (stdio): `python3 mcp_server.py` with env `SLED_SOURCE=mississippi` (or `uk_contracts_finder`).

**Categories/tags:** government, procurement, tenders, bids, RFP, govtech, open-data, OCDS.

**server.json:** `server.json` exists in the repo (set `OWNER` to your GitHub handle; create a UK variant). Used by the Official Registry path.
