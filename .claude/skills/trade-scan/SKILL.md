---
name: trade-scan
description: Auto mode of the trading desk. Checks data-source health and today's usage budget, updates the trade journal and the Judge's calibration, scans crypto (Binance), US stocks, NSE India and forex for the strongest movers in open markets, filters out trades your rules would block anyway (shorting rules, India forex rules, event guard, holidays, and the plan optimizer finding no workable plan), then runs the full desk on the top picks. Use when the user says /trade-scan, asks what to trade now, or asks the system to find trades by itself. Also the entry point for the scheduled 24/7 cloud routine.
argument-hint: "[markets=crypto,us,nse,forex] [picks=2] [intraday|swing]"
---

# Trade scan: health, budget, journal, find, filter, then the full desk on each pick

Arguments: `$ARGUMENTS`. Defaults: markets `crypto,us,nse,forex`, picks = `config/desk.json` → `budget.max_debates_per_scan`, style `intraday`.
Work from the project root. Use `python`, falling back to `python3`.

1. **Health:** `python tools/health.py`. If it exits 1, drop the markets listed under "do not trade markets" (all markets if the calendar is down); if none remain, report and stop.
1b. **Your trade requests:** `python tools/trade_requests.py list` → `ready` (debate these), `waiting` (intraday requests whose market is closed: leave them), `closed_now` (invalid or expired files it already moved to `requests/done/` with the reason).
2. **Budget:** `python tools/budget.py check`. Exit 1 → run `python tools/trade_requests.py status` and `python tools/render.py --index-only`, commit `requests docs` in the cloud, report "daily debate budget used up (your requests wait for tomorrow)" and stop. Otherwise picks = min(picks, debates left today).
3. **Journal:** `python tools/outcomes.py`, `python tools/calibration.py`, `python tools/quality.py`, `python tools/paper.py`.
3b. **Retake watcher:** `python tools/watch.py retake`. Entries in `debates/_retake_queue.json` come FIRST (mode `retake`, scan_reason = the queue's reason); remove each from the queue once its debate starts. If any fired and the PushNotification tool is available, notify: "Retake condition met for <symbol>: debating it again now."
4. **Candidates, in priority order:** (0) **your requests** from step 1b `ready`, oldest first, up to 3 per scan within the debates left today, on top of `picks` (mode `request`, `user_note` = the request's note, `user_plan` = its plan if given, its own direction, style and market, scan_reason "You asked for this trade"); (a) the retake queue; (b) your watchlist (already skips anything debated in the last 20 hours): `python tools/watch.py watchlist` (mode `watchlist`, `user_note` = the entry's note, its own direction and style); (c) the scanner: `python tools/scan.py --markets <markets> --pick 8 --out debates/_last_scan.json` (only markets open now; `direction` LONG if up today, SHORT if down).
   If `health.py` reported a critical source down, also notify (PushNotification) once: "Data source down: <names>; skipping <markets>."
5. **Filter before spending a debate** (go down the candidates in that priority order, then the scanner's `all_ranked`, until you have `picks` or run out), recording every skip with its reason:
   - SHORT not allowed by `risk.allow_short` for that market (`crypto`, `us`, `nse_intraday`/`nse_swing`, `forex`);
   - forex pair not in `india_forex_allowed_pairs` when `owner.residence` is `IN`;
   - `python tools/events.py --market <m> --symbol <s> --style <style>` status BLOCK;
   - `python tools/regime.py <s> --market <m> --style <style>`: calendar CLOSED_HOLIDAY;
   - **Your requests skip only the four hard checks above** (shorting, India forex, event BLOCK, holiday): a request that fails one is NOT debated; run `python tools/trade_requests.py done <file> --error "<the plain reason>"` so you see why on the dashboard. The optimizer filter below never applies to your requests: you asked, so the desk debates it and explains.
   - if `budget.skip_debate_when_optimizer_finds_nothing` is true: `python tools/optimizer.py --symbol <s> --market <m> --direction <d> --style <style>` status NO_PLAN or NO_EDGE (the code found no plan that passes your rules, so a debate would only confirm SKIP).
6. If nothing is left, write `debates/_last_scan_result.json` (format in step 8b, `debated: []`), run `python tools/render.py --index-only`, report the skipped candidates and reasons (this is a useful answer: "nothing worth debating right now"), run `python tools/trade_requests.py status` first, commit `debates/`, `docs/` and `requests/` in the cloud, and stop.
7. Tell the user which trades will be debated and why, plus the filtered-out list.
8. For each pick, one after another, follow `.claude/skills/trade-debate/SKILL.md` exactly (`"mode": "scan"`, `"scan_reason"`; your requests: `"mode": "request"`). After a request's debate is finished (final render done), run `python tools/trade_requests.py done <file> --id <ID>`; if its debate failed, `--error "<what went wrong>"`. Never mark a request done before its debate finishes, so a crashed run retries it next scan.
8b. Write `debates/_last_scan_result.json` for the dashboard: `{"scanned_utc": "<now>", "debated": [{"symbol", "market", "direction", "id"}], "skipped": [{"symbol", "market", "direction", "reason": "<one plain sentence>"}], "markets_open": [...], "health": "<OK|DEGRADED|DOWN>", "budget_left": n}`.
9. `python tools/trade_requests.py status`, then `python tools/render.py --all`. In the cloud: `git add debates docs requests && git commit -m "Scan <UTC time>: <TRADE FINAL_CALL, ...>" && git push origin HEAD:main`.
10. Reply with a short table (your requests first, plus any still waiting and why): proposed trade, market, Judge ruling, risk gate, **final call**, one-line reason, page link; then the filtered-out list; then the budget left today. End with: AI analysis, not financial advice, no orders placed.
