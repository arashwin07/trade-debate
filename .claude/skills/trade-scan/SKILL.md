---
name: trade-scan
description: Auto mode of the trading desk. Updates the trade journal, scans crypto (Binance), US stocks, NSE India and forex for the strongest movers in markets open now, filters out trades your rules would block anyway, then runs the full desk on the top picks (3-round Bull vs Bear debate with code-checked plans and Time Machine odds, Judge TAKE or SKIP, risk gate and ticket). Use when the user says /trade-scan, asks what to trade now, or asks the system to find trades by itself. Also the entry point for the scheduled 24/7 cloud routine.
argument-hint: "[markets=crypto,us,nse,forex] [picks=2] [intraday|swing]"
---

# Trade scan: journal, find, filter, then run the desk on each pick

Arguments: `$ARGUMENTS`. Defaults: markets `crypto,us,nse,forex`, picks `2`, style `intraday`.
Work from the project root. Use `python`, falling back to `python3`.

1. **Journal first:** `python tools/outcomes.py` (records what happened to earlier debates).
2. **Scan:** `python tools/scan.py --markets <markets> --pick 6 --out debates/_last_scan.json`. It only returns markets open now. Each candidate has a proposed `direction` (LONG if moving up today, SHORT if moving down).
3. **Filter before spending a debate** (go down `candidates`, then `all_ranked`, until you have `<picks>` or run out):
   - Skip a SHORT where `config/desk.json` → `risk.allow_short` is false for that market (`crypto`, `us`, `nse_intraday`/`nse_swing`, `forex`).
   - Skip a forex pair not in `india_forex_allowed_pairs` when `owner.residence` is `IN`.
   - Run `python tools/events.py --market <m> --symbol <s> --style <style>`; skip it if the status is BLOCK.
   - Record every skipped candidate with its reason.
4. If nothing is left, report the skipped candidates and reasons, commit `debates/_last_scan.json` in the cloud, and stop.
5. Tell the user which trades will be debated and why (`direction symbol: why`), plus the ones filtered out and why.
6. For each pick, one after another, follow `.claude/skills/trade-debate/SKILL.md` exactly (SYMBOL, direction, market from the candidate; style from the arguments; `meta.json` with `"mode": "scan"` and `"scan_reason"`).
7. `python tools/render.py --all`. In the cloud: `git add debates docs && git commit -m "Scan <UTC time>: <TRADE FINAL_CALL, ...>" && git push origin HEAD:main`.
8. Reply with a short table: proposed trade, market, Judge ruling, risk gate, **final call**, one-line reason, page link; then the filtered-out list. End with: AI analysis, not financial advice, no orders placed.
