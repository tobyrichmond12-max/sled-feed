# Active-seeding drafts (DO NOT auto-post — Toby posts, following each community's rules)

Framing for all: a genuine "I built a free tool, feedback welcome" — not an ad. Lead with
the problem, link once, ask a real question. Most communities ban link-drops and accounts
with no history, so post from an account with some karma/participation.

---
## Best-fit communities + their self-promo rules

| Community | Audience | Self-promo rule (check before posting) |
|---|---|---|
| **r/mcp** | MCP/agent builders | Tool shares OK if genuinely useful + not spammy; no low-effort ads. |
| **r/ClaudeAI** | Claude/agent users | "Built with Claude / tools" posts allowed; avoid pure promo; flair appropriately. |
| **r/govcon** | US gov contractors | Read rules — no blatant ads; helpful free resources usually OK; some self-promo limits/weekly threads. |
| **r/procurement** | Procurement pros | Professional; share as a useful resource + ask feedback, not a sales pitch. |
| **r/UKProcurement / r/smallbusinessuk** | UK buyers/suppliers | Low-volume; "free tool, feedback" tolerated if you engage. |
| **Hacker News — Show HN** | Builders | Must be try-able now; title `Show HN: …`; no marketing fluff; respond to comments. |
| **Indie Hackers (Show IH)** | Indie builders | "I built X" welcome; share the journey + ask for feedback. |
| **Apify Discord / community** | Apify users | Sharing your Actor is welcome in the right channel. |
| **MCP Discord (modelcontextprotocol)** | MCP devs | Share in a "show/showcase" channel; follow channel rules. |

Pick **2–3** (suggested: **r/mcp**, **Show HN or Indie Hackers**, and **r/govcon** for the buyer side).

---
## DRAFT 1 — r/mcp (or MCP Discord showcase channel)
**Title:** Free MCP tools for government procurement data (US + UK), with change-tracking

**Body:**
> I kept wanting an agent to answer "what government contracts match X, and which deadlines
> just changed?" — so I built two free MCP feeds:
> - **Mississippi** state bids/RFPs, and **UK** Contracts Finder tenders.
> - Tools: `search_opportunities`, `get_opportunity`, and the one I actually care about —
>   `list_recent_changes` (deadline changes, new awards, added documents over time).
> - Clean JSON, buyer org only (PII stripped), UK data under the Open Government Licence.
>
> They run as Apify Actors (usable via Apify's MCP server) and the change-feed is the part
> the official portals don't expose. Free during beta — I'd love feedback on the tool shape:
> is `list_recent_changes` the right primitive, and what other change types would you want?
> [link to one Actor]

---
## DRAFT 2 — Show HN / Indie Hackers
**Title:** Show HN: Free API + MCP tools for government tenders, with change-tracking

**Body:**
> Government bid portals show you today's open tenders but don't tell you when a **deadline
> moves**, when something is **awarded**, or when a new notice lands on a contract you're
> watching — which is exactly the part that costs suppliers money.
>
> I built two small free feeds that track procurement notices over time and expose the
> changes: **Mississippi** (US state) and the **UK** Contracts Finder. Each gives clean JSON
> plus MCP tools for agents (`search_opportunities`, `get_opportunity`, `list_recent_changes`).
> No PII (organisation names only); UK data is OGL v3.0.
>
> It's a deliberately narrow proving ground (one US state + the UK) before expanding. Free
> during beta. Feedback welcome — especially: would you pay for this for a state/country you
> sell into, and which change events matter most? [link]

---
## DRAFT 3 — r/govcon (buyer side, US)
**Title:** Built a free tool that tracks Mississippi bid deadline changes & new awards — useful?

**Body:**
> Quick one for folks who sell to state/local government: I got tired of re-checking the MS
> bid portal to catch deadline extensions and awards, so I built a free feed that **tracks
> what changed** — deadline moves, Open→Awarded, new documents — on top of the normal search.
> (There's a UK Contracts Finder version too.)
>
> It's free during beta and returns clean JSON / works with AI agents. Not selling anything —
> genuinely want to know if the **change-tracking** is useful enough to build out more states,
> and what you'd want it to alert on. Happy to add a state if there's interest. [link]

*(For r/govcon and r/procurement: confirm the subreddit allows the link; if not, post the
description and offer the link in comments / DM, and engage with replies rather than drop-and-go.)*
