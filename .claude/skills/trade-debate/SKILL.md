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
Right after writing meta.json, render once (`python tools/render.py debates/<ID>`) so the chat page exists and shows "Round 1 starting". If the Artifact tool is available, publish `debates/<ID>/debate.html` (first time with `icon: "chat"`; later steps republish the same file path).

For each round N = 1, 2, 3 (names: 1 = First look, 2 = Challenge, 3 = Final word):

**a. Debaters.** Launch **both agents in the same message** (two parallel Agent calls), `subagent_type` `bull-claude` and `bear-claude`. Prompt template:

> Proposed trade: **<TRADE>** (market `<market>`, style `<style>`). Market status: `<market_status>`.
> Debate folder: `debates/<ID>/`. This is Round N (<First look | Challenge | Final word>).
> Read `meta.json` and `snapshot.json`[, your previous round `r<N-1>_<you>.json`, your opponent's previous round `r<N-1>_<opponent>.json`, and the Judge's notes `r<N-1>_result.json`].
> Do fresh web research across several sources for this market, then write your Round N statement as JSON to `debates/<ID>/r<N>_<bull|bear>.json` following your output format. Write the chat messages in plain language a beginner understands.

Check both files parse: `python -c "import json,sys;[json.load(open(p,encoding='utf-8')) for p in sys.argv[1:]]" debates/<ID>/r<N>_bull.json debates/<ID>/r<N>_bear.json`. If one is missing or broken, re-run only that agent once and ask it to fix the file. Render and republish so the user sees the messages arrive.

**b. Round Result.** Launch one Agent, `subagent_type` `trade-judge`, `model: "sonnet"` (round results are quick):

> Mode A: Round Result for Round N. Proposed trade **<TRADE>**. Debate folder `debates/<ID>/`. Write `debates/<ID>/r<N>_result.json` following your Mode A format.

Validate it parses, then render and republish. **If running in the cloud**, also `git add debates docs && git commit -qm "<ID>: round N" && git push origin HEAD:main` so the live page on GitHub Pages updates during the debate.

## 3. The Judge
Launch one Agent with `subagent_type` `trade-judge`:

> Mode B: Final Conclusion. Proposed trade: **<TRADE>** (market `<market>`, style `<style>`). Debate folder: `debates/<ID>/`.
> Read meta.json, snapshot.json, all six statements r1_bull.json through r3_bear.json and the three round results. Re-check live data, fact-check both sides, and write your TAKE or SKIP ruling to `debates/<ID>/verdict.json` following your Mode B format, including all the plain-language fields.

Validate that `verdict.json` parses, re-running the Judge once if not.

## 4. Show the result
1. `python tools/render.py debates/<ID>` (this also rebuilds `docs/index.html`, the dashboard of all debates).
2. If the Artifact tool is available, republish `debates/<ID>/debate.html`.
3. If running in the cloud (scheduled routine) or the user asked to sync: `git add debates docs && git commit -m "Debate <ID>: <TAKE|SKIP>" && git push`. GitHub Pages then shows it at `<pages-url>/d/<ID>.html`.
4. Reply to the user with: the proposed trade, each round's result (leader and score), the final ruling (TAKE / SKIP) and confidence, the Judge's plain-language headline, the plan (if TAKE) or what would change the Judge's mind (if SKIP), and the page link. End with one line: this is AI analysis, not financial advice, and no order was placed.

Never place, simulate or route a real order. The user executes trades themselves.
