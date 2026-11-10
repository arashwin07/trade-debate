---
name: trade-debate
description: Debate a proposed trade you name (crypto, US stock, NSE stock or forex). Bull Claude argues FOR taking the trade, Bear Claude argues AGAINST it, over 3 rounds of live-evidence arguments, and the Judge decides TAKE or SKIP. The result is rendered as a viewable page. Use when the user says /trade-debate, or asks to debate, check or judge a specific trade.
argument-hint: SYMBOL [long|short] [intraday|swing] [crypto|us|nse|forex]
---

# Trade debate: Bull Claude (for) vs Bear Claude (against), the Judge decides TAKE or SKIP

Arguments: `$ARGUMENTS`. Parse them in any order as `SYMBOL [direction] [style] [market]`:
- direction: `long` (also `buy`) or `short` (also `sell`). Default `long`.
- style: `intraday` (default) or `swing`.
- market: `crypto`, `us`, `nse` or `forex`; if missing, auto-detect (e.g. `BTC` → crypto, `RELIANCE.NS` → nse, `EURUSD` → forex, `AAPL` → us). A bare Indian name such as `TATAMOTORS` needs `nse`; if a symbol is ambiguous, ask the user.
- The user may also give an entry, stop or target (e.g. `entry 74200 stop 73900`). Pass these into `meta.json` as `user_plan`; Bull defends that plan and may refine it.

The **proposed trade** is `<DIRECTION> <SYMBOL>`, for example `LONG BTC/USDT`. It is what gets debated.

Work from the project root (the folder that contains `tools/` and `.claude/`). Use `python` and fall back to `python3`.

## 1. Set up the debate folder and live snapshot
1. `ID` = UTC time, symbol and direction, e.g. `20261110-1205-BTC-LONG` (format `YYYYMMDD-HHMM-SYMBOL-DIRECTION`, symbol without `.NS`, `=X` or `/`).
2. Run `python tools/market_data.py <SYMBOL> --market <market> --style <style> --out debates/<ID>/snapshot.json`.
   If it fails, stop and tell the user the error (wrong symbol, data source down).
3. Write `debates/<ID>/meta.json`:
   `{"id": "<ID>", "symbol": "<display symbol>", "market": "...", "style": "...", "direction": "LONG|SHORT", "trade": "LONG BTC/USDT", "user_plan": {...} or null, "mode": "named", "created_utc": "<ISO time>"}`
   (In scan mode use `"mode": "scan"` and add `"scan_reason"`.)
4. Read the snapshot's `market_status`. If the market is CLOSED and the style is intraday, continue, but tell the agents in the prompt that the market is closed (the Judge treats it as a SKIP condition).

## 2. Three debate rounds
For each round N = 1, 2, 3, launch **both agents in the same message** (two Agent tool calls in parallel), `subagent_type` `bull-claude` and `bear-claude`. Prompt template (fill it in for each side):

> Proposed trade: **<TRADE>** (market `<market>`, style `<style>`). Market status: `<market_status>`.
> Debate folder: `debates/<ID>/`. This is Round N (<Opening | Rebuttal | Closing>).
> Read `meta.json` and `snapshot.json`[, your previous round `r<N-1>_<you>.json`, and your opponent's previous round `r<N-1>_<opponent>.json`].
> Do fresh web research across several sources for this market, then write your Round N statement as JSON to `debates/<ID>/r<N>_<bull|bear>.json` following your output format.

After each round:
- Check both files parse: `python -c "import json,sys;[json.load(open(p,encoding='utf-8')) for p in sys.argv[1:]]" debates/<ID>/r<N>_bull.json debates/<ID>/r<N>_bear.json`. If one is missing or broken, re-run only that agent once and ask it to fix the file.
- Render progress: `python tools/render.py debates/<ID>`. If the Artifact tool is available, publish `debates/<ID>/debate.html` (first time with `icon: "chart"`, later rounds republish the same file path) so the user can watch the debate fill in.

## 3. The Judge
Launch one Agent with `subagent_type` `trade-judge`:

> Proposed trade: **<TRADE>** (market `<market>`, style `<style>`). Debate folder: `debates/<ID>/`.
> Read meta.json, snapshot.json and all six round files r1_bull.json through r3_bear.json. Re-check live data, fact-check both sides, and write your TAKE or SKIP ruling to `debates/<ID>/verdict.json` following your output format.

Validate that `verdict.json` parses, re-running the Judge once if not.

## 4. Show the result
1. `python tools/render.py debates/<ID>` (this also rebuilds `docs/index.html`, the dashboard of all debates).
2. If the Artifact tool is available, republish `debates/<ID>/debate.html`.
3. If running in the cloud (scheduled routine) or the user asked to sync: `git add debates docs && git commit -m "Debate <ID>: <TAKE|SKIP>" && git push`. GitHub Pages then shows it at `<pages-url>/d/<ID>.html`.
4. Reply to the user with: the proposed trade, the ruling (TAKE / SKIP) and confidence, Bull's and Bear's one-line closing theses, the trade plan (if TAKE) or the retake conditions (if SKIP), the main reason the Judge gave, and the page link. End with one line: this is AI analysis, not financial advice, and no order was placed.

Never place, simulate or route a real order. The user executes trades themselves.
