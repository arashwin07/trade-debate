---
name: trade-debate
description: The full pre-trade desk for one proposed trade you name (crypto, US stock, NSE stock or forex). Live data + event guard, then Bull Claude argues FOR the trade and Bear Claude AGAINST over 3 rounds, with code-checked plan math and Time Machine odds after every round, a Judge result per round, the Judge's final TAKE or SKIP, then the risk gate (costs, position size, your limits) and a plain-language ticket. Rendered as a viewable chat page. Use when the user says /trade-debate, or asks to debate, check or judge a specific trade.
argument-hint: SYMBOL [long|short] [intraday|swing] [crypto|us|nse|forex]
---

# Trade desk: one proposed trade, start to finish

**Rule: the agents ARGUE, the code CALCULATES.** Every money number (reward-to-risk, stop size, costs, position size, odds, limits) comes from `tools/desk.py`, `tools/timemachine.py` and `tools/events.py`. Never type such numbers yourself; read them from the files.

Arguments: `$ARGUMENTS`. Parse them in any order as `SYMBOL [direction] [style] [market]`:
- direction: `long` (also `buy`) or `short` (also `sell`). Default `long`.
- style: `intraday` (default) or `swing`.
- market: `crypto`, `us`, `nse` or `forex`; if missing, auto-detect (e.g. `BTC` → crypto, `RELIANCE.NS` → nse, `EURUSD` → forex, `AAPL` → us). A bare Indian name such as `TATAMOTORS` needs `nse`; if a symbol is ambiguous, ask the user.
- The user may also give an entry, stop or target (e.g. `entry 74200 stop 73900`). Put them in `meta.json` as `user_plan`; Bull defends that plan and may refine it.

The **proposed trade** is `<DIRECTION> <SYMBOL>`, for example `LONG BTC/USDT`.

Work from the project root (the folder with `tools/`, `config/` and `.claude/`). Use `python`, falling back to `python3`. If any tool fails, stop and tell the user the exact error; never fill a gap with a guessed number.

## 1. Set up: live data and event guard
1. `ID` = `YYYYMMDD-HHMM-SYMBOL-DIRECTION` in UTC, symbol without `.NS`, `=X` or `/` (e.g. `20261110-1205-BTC-LONG`).
2. `python tools/market_data.py <SYMBOL> --market <market> --style <style> --out debates/<ID>/snapshot.json`
3. `python tools/events.py --market <market> --symbol <SYMBOL> --style <style> --out debates/<ID>/events.json`
4. Write `debates/<ID>/meta.json`: `{"id", "symbol", "market", "style", "direction": "LONG|SHORT", "trade": "LONG BTC/USDT", "user_plan": {...} or null, "mode": "named", "created_utc"}` (scan mode: `"mode": "scan"` and `"scan_reason"`).
5. Render (`python tools/render.py debates/<ID>`). If the Artifact tool is available, publish `debates/<ID>/debate.html` (first time with `icon: "chat"`, later republish the same path).
6. If `events.json` says BLOCK or the market is CLOSED for an intraday trade, still run the debate (the user wants the analysis) but put that fact in every agent prompt.

## 2. Three rounds (1 = First look, 2 = Challenge, 3 = Final word)
For each round N:

**a. Debaters.** Launch both in the same message (two parallel Agent calls), `subagent_type` `bull-claude` and `bear-claude`:

> Proposed trade: **<TRADE>** (market `<market>`, style `<style>`). Market status: `<market_status>`. Event guard: `<status>: <plain>`.
> Debate folder: `debates/<ID>/`. This is Round N (<name>).
> Read `meta.json`, `snapshot.json`, `events.json`[, your previous round `r<N-1>_<you>.json`, your opponent's `r<N-1>_<opponent>.json`, the Judge's notes `r<N-1>_result.json` and the desk's check `desk_r<N-1>.json`].
> Do fresh web research across several sources for this market, then write your Round N statement as JSON to `debates/<ID>/r<N>_<bull|bear>.json` following your output format (Bull: `plan_numbers` is required). Chat messages in plain language a beginner understands.

Check both parse: `python -c "import json,sys;[json.load(open(p,encoding='utf-8')) for p in sys.argv[1:]]" debates/<ID>/r<N>_bull.json debates/<ID>/r<N>_bear.json`. Re-run a missing or broken one once. Render and republish.

**b. Desk check (code).** `python tools/desk.py analyze debates/<ID> --round N` → `desk_r<N>.json`: Bull's plan math, issues, and Time Machine odds (10,000 replays + real history). If it reports that Bull's plan has no usable numbers, re-run Bull once asking for `plan_numbers`. Render and republish.

**c. Round Result.** One Agent, `subagent_type` `trade-judge`, `model: "sonnet"`:

> Mode A: Round Result for Round N. Proposed trade **<TRADE>**. Debate folder `debates/<ID>/`. Use `desk_r<N>.json` and `events.json` as the referee's numbers. Write `debates/<ID>/r<N>_result.json` following your Mode A format.

Validate, render, republish. **In the cloud** also `git add debates docs && git commit -qm "<ID>: round N" && git push origin HEAD:main` so the live page updates.

## 3. The Judge's final conclusion
One Agent, `subagent_type` `trade-judge`:

> Mode B: Final Conclusion. Proposed trade: **<TRADE>** (market `<market>`, style `<style>`). Debate folder: `debates/<ID>/`.
> Read meta.json, snapshot.json, events.json, all six statements, the three round results and desk_r3.json. Re-check live data, fact-check both sides, and write your TAKE or SKIP ruling to `debates/<ID>/verdict.json` following your Mode B format, including `trade_plan_numbers` and all plain-language fields.

Validate (re-run once if broken).

## 4. Risk gate and ticket (code)
`python tools/desk.py gate debates/<ID>` → `desk_final.json`: fresh price, event guard refresh, costs for this market and broker, position size from `config/desk.json`, every risk rule (PASS / WARN / BLOCK with plain reasons), the **final call** (TAKE only if the Judge said TAKE and the gate passed) and, for a TAKE, a plain-language ticket the user can place themselves.

## 5. Show the result
1. `python tools/render.py debates/<ID>` (also rebuilds the dashboard). Republish the artifact if available.
2. In the cloud: `git add debates docs && git commit -m "Debate <ID>: <final call>" && git push origin HEAD:main`.
3. Reply with: the proposed trade, the event guard, each round's result, the Time Machine odds of the final plan, the Judge's ruling and confidence, the risk gate result with any block reasons, the **final call**, the ticket (if TAKE) or what would change the Judge's mind (if SKIP), and the page link. If capital is not set in `config/desk.json`, say so in one line. End with: AI analysis, not financial advice; no order was placed.

Never place, simulate or route a real order. The user executes trades themselves.
