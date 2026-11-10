---
name: trade-debate
description: Run the Bull Claude vs Bear Claude trade debate on an asset you name (crypto, US stock, NSE stock or forex), with 3 rounds of live-evidence arguments and a final BUY / SELL / NO TRADE ruling from the Judge, rendered as a viewable page. Use when the user says /trade-debate SYMBOL, or asks to debate, analyse or judge a specific trade.
argument-hint: SYMBOL [intraday|swing] [crypto|us|nse|forex]
---

# Trade debate: Bull Claude vs Bear Claude, ruled by the Judge

Arguments: `$ARGUMENTS`. Parse them as `SYMBOL [style] [market]`:
- style: `intraday` (default) or `swing`
- market: `crypto`, `us`, `nse` or `forex`; if missing, auto-detect (e.g. `BTC` → crypto, `RELIANCE.NS` → nse, `EURUSD` → forex, `AAPL` → us). A bare Indian name such as `TATAMOTORS` needs `nse`; if a symbol is ambiguous, ask the user.

Work from the project root (the folder that contains `tools/` and `.claude/`). Use `python` and fall back to `python3`.

## 1. Set up the debate folder and live snapshot
1. `ID` = UTC time plus symbol, e.g. `20261110-1205-BTC` (format `YYYYMMDD-HHMM-SYMBOL`, symbol without `.NS`, `=X` or `/`).
2. Run `python tools/market_data.py <SYMBOL> --market <market> --style <style> --out debates/<ID>/snapshot.json`.
   If it fails, stop and tell the user the error (wrong symbol, data source down).
3. Write `debates/<ID>/meta.json`: `{"id": "<ID>", "symbol": "...", "market": "...", "style": "...", "mode": "named", "created_utc": "<ISO time>"}` (in scan mode use `"mode": "scan"` and add `"scan_reason"`).
4. Read the snapshot's `market_status`. If the market is CLOSED and the style is intraday, continue anyway, but tell the agents in the prompt that the market is closed (the Judge treats this as a NO TRADE condition).

## 2. Three debate rounds
For each round N = 1, 2, 3, launch **both agents in the same message** (two Agent tool calls in parallel), `subagent_type` `bull-claude` and `bear-claude`. Prompt template (fill it in for each side):

> Debate folder: `debates/<ID>/`. Asset: `<SYMBOL>` (market `<market>`, style `<style>`). Market status: `<market_status>`.
> This is Round N (<Opening | Rebuttal | Closing>).
> Read `debates/<ID>/snapshot.json`[, your previous round `r<N-1>_<you>.json`, and your opponent's previous round `r<N-1>_<opponent>.json`].
> Do fresh web research across several sources for this market, then write your Round N statement as JSON to `debates/<ID>/r<N>_<bull|bear>.json` following your output format.

After each round:
- Check that both files exist and parse: `python -c "import json,sys;[json.load(open(p,encoding='utf-8')) for p in sys.argv[1:]]" debates/<ID>/r<N>_bull.json debates/<ID>/r<N>_bear.json`. If one is missing or broken, re-run only that agent once and ask it to fix the file.
- Render progress: `python tools/render.py debates/<ID>`. If the Artifact tool is available, publish `debates/<ID>/debate.html` (first time with `icon: "chart"`, later rounds republish the same file path) so the user can watch the debate fill in.

## 3. The Judge
Launch one Agent with `subagent_type` `trade-judge`:

> Debate folder: `debates/<ID>/`. Asset `<SYMBOL>` (market `<market>`, style `<style>`).
> Read snapshot.json and all six round files r1_bull.json through r3_bear.json. Re-check live data, fact-check both sides, and write your ruling to `debates/<ID>/verdict.json` following your output format.

Validate `verdict.json` parses, re-running the Judge once if not.

## 4. Show the result
1. `python tools/render.py debates/<ID>` (this also rebuilds `docs/index.html`, the dashboard of all debates).
2. If the Artifact tool is available, republish `debates/<ID>/debate.html`.
3. If running in the cloud (scheduled routine) or the user asked to sync: `git add debates docs && git commit -m "Debate <ID>: <DECISION>" && git push`. GitHub Pages then shows it at `<pages-url>/d/<ID>.html`.
4. Reply to the user with: the ruling (BUY / SELL / NO TRADE) and confidence, the Bull's and Bear's one-line theses from Round 3, the trade plan (entry, stop, targets, reward-to-risk), the main reason the Judge gave, and the page link. End with one line: this is AI analysis, not financial advice, and no order was placed.

Never place, simulate or route a real order. The user executes trades themselves.
