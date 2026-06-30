# UK Government Tenders & Contracts Finder API — with Change Tracking

**Search UK public-sector tenders and awards from Contracts Finder — and get the one
thing the portal won't push you: what CHANGED.** Deadline changes, new awards, and added
notices, as a structured API and MCP tools for AI agents.

> Looking for: UK government tenders API · Contracts Finder API · UK public sector contracts ·
> OCDS tender data · government procurement / bids data · RFP / ITT tracking · tender alerts.
> This Actor delivers it as clean JSON, grouped by procurement (OCID).

## The problem this solves
UK Contracts Finder lists current tenders and awards — but it **doesn't proactively tell
you when a deadline moves, when something is awarded, or when a new notice lands** on a
procurement you're watching. For suppliers and bid teams, a missed deadline change or a
missed award is lost business. This feed **tracks every notice over time** and exposes
those change events directly.

## What you can do
- **Search UK government tenders** by category (CPV), keyword, status, and dates.
- **Get a full notice** by ID (OCID), including document links and the live notice URL.
- **Track what changed** — deadline changes, new awards, added documents — grouped by the
  procurement's stable **OCID** so a tender and its later award line up. *The differentiator.*

## MCP tools (for AI agents / Claude / agent builders)
Exposes Model Context Protocol tools so an agent can query UK procurement directly:
- `search_opportunities(category, keyword, status, posted_after, due_after, due_before)`
- `get_opportunity(solicitation_id)`  *(solicitation_id = OCID)*
- `list_recent_changes(since)` — the change feed

## Example input
```json
{ "tool": "search_opportunities", "status": "Open", "keyword": "facilities", "limit": 5 }
```
## Example output (one record)
```json
{
  "solicitation_id": "ocds-b5fd17-8718ec9a-...",
  "title": "FM Procurement Consultancy Support",
  "agency": "Watford Borough Council",
  "category": "Procurement consultancy services",
  "status": "Awarded",
  "estimated_value": 50000,
  "value_currency": "GBP",
  "due_date": "2026-03-02T00:00:00+00:00",
  "source_url": "https://www.contractsfinder.service.gov.uk/notice/336cb675-1fe7-452f-b23d-2f87addeeec1"
}
```
## Example change event (`list_recent_changes`)
```json
{ "event": "deadline_changed", "solicitation_id": "ocds-b5fd17-8718ec9a-...",
  "old_due_date": "2026-02-23T00:00:00+00:00", "new_due_date": "2026-03-02T00:00:00+00:00" }
```

## Data schema (per tender)
`solicitation_id` (OCID), `title`, `agency` (**buyer organisation only**), `category`
(CPV description), `posted_date` / `due_date` (ISO-8601 with explicit timezone),
`status` (Open / Closed / Awarded), `estimated_value` (**present for most UK notices**, GBP),
`document_links`, `source` / `source_url` (the live notice page).

**No personal data.** Buyer **contact** names/emails/phones are **stripped at ingestion**
and re-checked at storage; the free-text `description` (which can contain emails) is
**dropped**. Only the buying **organisation name** and solicitation data are served.

## Coverage & freshness
Official **UK Contracts Finder** OCDS API (Cabinet Office) — central government, local
councils, NHS, education and other public bodies. **National, high volume.** Refreshed
daily; history accumulates as it runs (early-access window of recent notices).

## Access
**Free during early access (beta).** Usage limits or pricing may be introduced later, with
notice. (Not "free forever," just free for now.)

## Reliability
A built-in monitor watches for upstream breakage and PII drift; if something looks wrong it
**stops serving and returns "temporarily unavailable" rather than serve stale or wrong data.**

## Licence / attribution
Contains public sector information from UK **Contracts Finder**, © Crown copyright, licensed
under the **Open Government Licence v3.0** (commercial reuse permitted).
http://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/

---
*Keywords: UK government tenders API, Contracts Finder API, UK public sector contracts, OCDS
data, procurement data, government bids, ITT / RFP / RFQ tracking, tender alerts, GovTech.*
