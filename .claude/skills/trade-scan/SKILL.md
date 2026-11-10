---
name: trade-scan
description: Auto mode for the trade debate. Scans crypto (Binance), US stocks, NSE India and forex for the strongest movers in markets that are open now, proposes a trade for each (following the move), then runs the full 3-round debate (Bull Claude for the trade, Bear Claude against) and the Judge's TAKE or SKIP ruling. Use when the user says /trade-scan, asks what to trade now, or asks the system to find trades by itself. Also the entry point for the scheduled 24/7 cloud routine.
argument-hint: "[markets=crypto,us,nse,forex] [picks=2] [intraday|swing]"
---

# Trade scan: find candidate trades, then debate each one

Arguments: `$ARGUMENTS`. Defaults: markets `crypto,us,nse,forex`, picks `2`, style `intraday`.

Work from the project root. Use `python`, falling back to `python3`.

1. Run `python tools/scan.py --markets <markets> --pick <picks> --out debates/_last_scan.json`.
   It only returns markets that are open right now (crypto always, forex on weekdays, US and NSE during their sessions). Each candidate has a proposed `direction` (LONG if it is moving up today, SHORT if moving down).
2. If `candidates` is empty, report "no open market had a qualifying mover" with the scan notes, commit `debates/_last_scan.json` if running in the cloud, and stop.
3. Tell the user which trades were proposed and why (`direction symbol: why`), in one short list.
4. For each candidate, one after another, follow the `/trade-debate` skill procedure exactly (`.claude/skills/trade-debate/SKILL.md`) with:
   - SYMBOL = candidate `symbol`, direction = candidate `direction`, market = candidate `market`, style from the arguments
   - `meta.json` with `"mode": "scan"` and `"scan_reason": "<why>"`
5. After all debates, run `python tools/render.py --index-only`. If running in the cloud: `git add debates docs && git commit -m "Scan <UTC time>: <TRADE TAKE|SKIP, ...>" && git push`.
6. Reply with a short table: proposed trade, market, ruling (TAKE / SKIP), confidence, one-line reason, and the link to each debate page. End with: AI analysis, not financial advice, no orders placed.
