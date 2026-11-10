---
name: trade-scan
description: Auto mode of the trading desk. Checks data-source health and today's usage budget, updates the trade journal and the Judge's calibration, scans crypto (Binance), US stocks, NSE India and forex for the strongest movers in open markets, filters out trades your rules would block anyway (shorting rules, India forex rules, event guard, holidays, and the plan optimizer finding no workable plan), then runs the full desk on the top picks. Use when the user says /trade-scan, asks what to trade now, or asks the system to find trades by itself. Also the entry point for the scheduled 24/7 cloud routine.
argument-hint: "[markets=crypto,us,nse,forex] [picks=2] [intraday|swing]"
---

# Trade scan: health, budget, journal, find, filter, then the full desk on each pick

Arguments: `$ARGUMENTS`. Defaults: markets `crypto,us,nse,forex`, picks = `config/desk.json` → `budget.max_debates_per_scan`, style `intraday`.
Work from the project root. Use `python`, falling back to `python3`.

1. **Health:** `python tools/health.py`. If it exits 1, drop the markets listed under "do not trade markets" (all markets if the calendar is down); if none remain, report and stop.
2. **Budget:** `python tools/budget.py check`. Exit 1 → report "daily debate budget used up" and stop. Otherwise picks = min(picks, debates left today).
3. **Journal:** `python tools/outcomes.py` then `python tools/calibration.py`.
4. **Scan:** `python tools/scan.py --markets <markets> --pick 8 --out debates/_last_scan.json` (only markets open now). Each candidate has a `direction` (LONG if up today, SHORT if down).
5. **Filter before spending a debate** (go down `candidates`, then `all_ranked`, until you have `picks` or run out), recording every skip with its reason:
   - SHORT not allowed by `risk.allow_short` for that market (`crypto`, `us`, `nse_intraday`/`nse_swing`, `forex`);
   - forex pair not in `india_forex_allowed_pairs` when `owner.residence` is `IN`;
   - `python tools/events.py --market <m> --symbol <s> --style <style>` status BLOCK;
   - `python tools/regime.py <s> --market <m> --style <style>`: calendar CLOSED_HOLIDAY;
   - if `budget.skip_debate_when_optimizer_finds_nothing` is true: `python tools/optimizer.py --symbol <s> --market <m> --direction <d> --style <style>` status NO_PLAN or NO_EDGE (the code found no plan that passes your rules, so a debate would only confirm SKIP).
6. If nothing is left, report the skipped candidates and reasons (this is a useful answer: "nothing worth debating right now"), commit `debates/_last_scan.json` and `docs/` in the cloud, and stop.
7. Tell the user which trades will be debated and why, plus the filtered-out list.
8. For each pick, one after another, follow `.claude/skills/trade-debate/SKILL.md` exactly (`"mode": "scan"`, `"scan_reason"`).
9. `python tools/render.py --all`. In the cloud: `git add debates docs && git commit -m "Scan <UTC time>: <TRADE FINAL_CALL, ...>" && git push origin HEAD:main`.
10. Reply with a short table: proposed trade, market, Judge ruling, risk gate, **final call**, one-line reason, page link; then the filtered-out list; then the budget left today. End with: AI analysis, not financial advice, no orders placed.
