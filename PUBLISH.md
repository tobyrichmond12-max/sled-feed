# Phase 6 — publish steps (one-time, needs YOUR account credentials)

Everything is built and publish-ready. Publishing is an outward-facing action under
your account, and no Apify/GitHub/MCP credentials exist on this box, so these final
commands need you (or a token you hand me). Pick a path; Apify is the fastest route
to a callable + billable listing.

## Path A — Apify Actor (fastest callable + metered listing)
Prereq: an Apify account.
```bash
npm i -g apify-cli            # node 22 present on this box
apify login                   # opens browser, or: apify login -t <APIFY_TOKEN>
cd /home/thoth/sled-feed
apify push                    # builds from .actor/ + Dockerfile, creates the Actor
```
Then in the Apify console: set the Actor **public**, configure **pay-per-event**
pricing (events: `search_opportunities`, `get_opportunity`, `list_recent_changes`
— matching billing.PRICING), paste LISTING.md as the README/description.
→ Live URL: `https://apify.com/<your-username>/mississippi-procurement-feed`

If you give me `APIFY_TOKEN`, I can run `apify login -t … && apify push` myself.

## Path B — MCP registry / directories
Prereq: a public GitHub repo (this folder is already a git repo, committed).
```bash
gh repo create sled-feed --public --source=. --push     # or add a remote + git push
```
Then:
- Set `OWNER` in `server.json` to your GitHub handle.
- Submit to the official MCP registry (needs the server in a package registry — see
  server.json `_publish_note`) and/or list on Smithery (connect the GitHub repo).
- Auto-crawling directories (Glama, PulseMCP) index public MCP repos automatically.

If you give me `gh auth` (or create the repo + remote), I can push and submit.

## What I need from you (one of):
1. `APIFY_TOKEN`  → I publish the Actor and return the live URL, or
2. a GitHub repo (auth/remote) → I push + submit to the MCP directories.

Until then: the call path, metering, health gate, and instrumentation are all
verified locally (see phase6_report.py), and the listing copy is final in LISTING.md.
