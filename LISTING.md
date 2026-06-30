# Mississippi Government Bids & Procurement Tracker — with Change Tracking

**Search live Mississippi government bids, RFPs and contract opportunities — and get
the one thing the state portal won't push you: what CHANGED.** Deadline extensions,
new awards, and posted addenda, as a structured API and MCP tools for agents.

> Looking for: Mississippi government bids API · Mississippi procurement / RFP data ·
> state government contract opportunities · solicitation tracking · bid deadline alerts ·
> public sector tender data. This Actor delivers all of it as clean JSON.

## The problem this solves
The official Mississippi (DFA) bid portal shows you today's open solicitations — but it
**doesn't tell you when a deadline moves, when a bid is awarded, or when an addendum
drops** on a contract you're watching. If you sell to government, missing a deadline
change or a recompete is lost revenue. This feed **tracks every solicitation over time**
and exposes those change events directly.

## What you can do
- **Search Mississippi government bids** by category, keyword, status, and dates.
- **Get a full solicitation** by ID, including document links and the official notice URL.
- **Track what changed** — deadline changes, new awards (Open → Awarded), added documents —
  grouped per solicitation. *This is the differentiator; free portals don't surface it.*

## MCP tools (for AI agents / Claude / agent builders)
This Actor exposes Model Context Protocol tools, so an agent can query procurement data directly:
- `search_opportunities(category, keyword, status, posted_after, due_after, due_before)`
- `get_opportunity(solicitation_id)`
- `list_recent_changes(since)` — the change feed

## Example input
```json
{ "tool": "search_opportunities", "status": "Open", "category": "INFORMATION TECHNOLOGY", "limit": 5 }
```
## Example output (one record)
```json
{
  "solicitation_id": "1601-26-R-RFIN-00066",
  "title": "Sole Source No. 4751 ... SPIRIT Management Information System ...",
  "agency": "Mississippi Department of Health",
  "category": "INFORMATION TECHNOLOGY (IT)",
  "status": "Open",
  "due_date": "2026-06-30T15:00:00-05:00",
  "due_timezone": "America/Chicago",
  "document_links": [{ "label": "Solicitation PDF", "url": "https://.../SYN_BID_FORM_....PDF" }],
  "source_url": "https://www.ms.gov/dfa/contract_bid_search/Bid/Details/45668"
}
```
## Example change event (`list_recent_changes`)
```json
{ "event": "deadline_changed", "solicitation_id": "1601-26-R-RFIN-00066",
  "old_due_date": "2026-06-30T15:00:00-05:00", "new_due_date": "2026-07-07T15:00:00-05:00" }
```

## Data schema (per solicitation)
`solicitation_id`, `title`, `agency` (buying organisation), `category`, `bid_type`,
`posted_date` / `due_date` (ISO-8601 with explicit Central timezone + closing time),
`status` (Open / Closed / Awarded / Archived), `document_links`, `source` / `source_url`.
**`estimated_value` is not published by this source** (returned `null`, never a filterable field).

**No personal data.** Buyer contact names/emails/phones in the source are stripped at
ingestion and re-checked at storage; only solicitation data and the buying **organisation
name** are served.

## Coverage & freshness
Official **Mississippi DFA Contract Bid Search** (`ms.gov`) — all state agencies,
universities and participating local entities. Refreshed daily; each record carries
`first_seen` / `last_seen`. Single-state by design (a focused, reliable feed).

## Access
**Free during early access (beta).** Usage limits or pricing may be introduced later, with
notice. (Not "free forever," just free for now.)

## Reliability
A built-in monitor watches for upstream breakage (renamed fields, response-shape changes,
record-count crashes, new status values, or PII drifting toward the output). If something
looks wrong, **it stops serving and returns "temporarily unavailable" rather than hand you
stale or wrong data.**

---
*Keywords: Mississippi government bids, MS procurement, state RFP, solicitations, government
contract opportunities, bid alerts, deadline tracking, public sector tenders, SLED procurement API.*
