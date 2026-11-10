---
name: trade-journal
description: The trade journal and track record. Checks what really happened after every past debate (did the price reach the entry, then the target or the stop first?), for TAKE and SKIP calls alike, and summarises how often the Judge was right. Use when the user says /trade-journal, "how are we doing", "track record", "did the trades work", "was the Judge right".
---

# Trade journal

From the project root:
1. `python tools/outcomes.py` updates `outcome.json` in every finished debate and prints the track record.
2. `python tools/render.py --all` refreshes every page and the dashboard's track record.
3. In the cloud: `git add debates docs && git commit -qm "Journal update" && git push origin HEAD:main`.

Tell the user, in plain words:
- **TAKE calls:** how many resolved, wins and losses, average result in R (R = multiples of the risk; +2R means won twice what was risked).
- **SKIP calls:** how many would have lost (good skips) and how many would have won (missed chances).
- Trades still pending or never filled.
- One honest line on what the numbers mean: with few results this is not yet proof of anything; it needs dozens of trades.
