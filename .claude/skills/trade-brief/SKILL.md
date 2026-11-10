---
name: trade-brief
description: The morning brief before the bell (NSE or US) or for all markets: data-source health, market mood (indexes, fear gauges, dollar), today's major scheduled events, overnight crypto and forex moves, the watchlist with nearest floors and ceilings and volatility, skipped ideas still being watched, the Judge's track record and the practice account. Use when the user says /trade-brief, "morning brief", "what's happening today", "before the open". Also run by the scheduled brief routines.
argument-hint: "[nse|us|all]"
---

# Morning brief

From the project root (default `all`):
1. `python tools/watch.py retake` (refresh the watched retake ideas).
2. `python tools/brief.py <nse|us|all>` → `docs/brief.html` (website) and `docs/brief_artifact.html` (artifact version).
3. If the Artifact tool is available, publish `docs/brief_artifact.html` (first time `icon: "sun"`).
4. In the cloud: `git add docs && git commit -qm "Brief <which> <UTC date>" && git push origin HEAD:main`; the page is `<pages-url>/brief.html`. If the PushNotification tool is available, send one line: the mood, the number of major events today, and the page link.
5. Reply in plain words, in this order: data health; the market mood in one sentence per market; today's major events with times in India time (IST); overnight moves; each watchlist entry (price, nearest floor and ceiling, volatility, the user's note); retake ideas being watched; the track record and practice account. No trade recommendations here: the debates do that.
