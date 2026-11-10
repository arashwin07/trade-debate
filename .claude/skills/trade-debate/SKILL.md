---
name: trade-debate
description: The full pre-trade desk for one proposed trade you name (crypto, US stock, NSE stock or forex). Code first (live data, levels, volatility and holidays, news, event guard, plan optimizer), then Bull Claude argues FOR and Bear Claude AGAINST over 3 rounds with every agent file validated, every cited number checked by code, plan math and Time Machine odds after each round, a Judge result per round, the Judge's final TAKE or SKIP, then the risk gate (costs, size, your limits) and a plain-language ticket. Rendered as a viewable chat page. Use when the user says /trade-debate, or asks to debate, check or judge a specific trade.
argument-hint: SYMBOL [long|short] [intraday|swing] [crypto|us|nse|forex]
---

# Trade desk: one proposed trade, start to finish

**Rule: the agents ARGUE, the code CALCULATES.** Every money number comes from the tools in `tools/`. Never type such numbers yourself; read them from the files. If any tool fails, stop and tell the user the exact error; never fill a gap with a guess. Every tool writes a line to `debates/<ID>/audit.log`.

Arguments: `$ARGUMENTS`, parsed in any order as `SYMBOL [direction] [style] [market]`:
- direction `long` (also `buy`) or `short` (also `sell`), default `long`; style `intraday` (default) or `swing`;
- market `crypto`, `us`, `nse`, `forex`, else auto-detect (`BTC` → crypto, `RELIANCE.NS` → nse, `EURUSD` → forex, `AAPL` → us). A bare Indian name like `TATAMOTORS` needs `nse`; ask if ambiguous.
- The user may give entry/stop/target: store as `user_plan` in `meta.json`; Bull defends it and may refine it.

The **proposed trade** is `<DIRECTION> <SYMBOL>`, e.g. `LONG BTC/USDT`. Work from the project root; use `python`, falling back to `python3`.
Models (from `config/desk.json` → `budget.models`): debaters `sonnet`, round results `sonnet`, final Judge `opus`.

## 1. Code first (all saved in `debates/<ID>/`)
`ID` = `YYYYMMDD-HHMM-SYMBOL-DIRECTION` in UTC (symbol without `.NS`, `=X`, `/`).
1. `python tools/market_data.py <SYMBOL> --market <m> --style <s> --out debates/<ID>/snapshot.json`
2. `python tools/events.py --market <m> --symbol <SYMBOL> --style <s> --out debates/<ID>/events.json`
3. `python tools/regime.py <SYMBOL> --market <m> --style <s> --out debates/<ID>/regime.json` (volatility level, size multiplier, holiday / half-day)
4. `python tools/levels.py <SYMBOL> --market <m> --style <s> --out debates/<ID>/levels.json`
5. `python tools/news.py <SYMBOL> --market <m> --style <s> [--name "<company name from the snapshot>"] --out debates/<ID>/news.json`
6. `python tools/context.py <SYMBOL> --market <m> --direction <d> --out debates/<ID>/context.json` (is the wider market a tailwind or headwind?) and `python tools/fundamentals.py <SYMBOL> --market <m> --out debates/<ID>/fundamentals.json` (the business or coin behind the price).
6b. Write `meta.json`: `{"id", "symbol", "market", "style", "direction", "trade", "user_plan" or null, "user_note": "<the user's own view, from the command or config/watchlist.json>" or null, "mode": "named" | "scan" | "watchlist" | "retake", "scan_reason"?, "created_utc"}`
7. `python tools/optimizer.py debates/<ID>` → `optimizer.json`: the best plans built from real levels that pass your rules and the Time Machine, or NO_PLAN / NO_EDGE.
8. Render (`python tools/render.py debates/<ID>`); publish `debates/<ID>/debate.html` with the Artifact tool if available (first time `icon: "chat"`, later republish the same path).
Facts every agent prompt carries: market status, holiday/half-day, event guard, volatility level, optimizer status.

## 2. Three rounds (1 = First look, 2 = Challenge, 3 = Final word)
Common prompt lines for every debater call:
> Proposed trade: **<TRADE>** (market `<m>`, style `<s>`). Market: `<status>`. Event guard: `<status>: <plain>`. Volatility: `<level>`. Optimizer: `<status>`.
> Debate folder `debates/<ID>/`. Read `meta.json` (including the user's own note, if any), `snapshot.json`, `events.json`, `regime.json`, `levels.json`, `news.json`, `context.json`, `fundamentals.json`, `optimizer.json`[ and from Round 2: your previous round, your opponent's latest round, the Judge's `r<N-1>_result.json`, the desk's `desk_r<N-1>.json` and the claim check `claims_r<N-1>.json`].
> For fresh numbers run `python tools/market_data.py <SYMBOL> --market <m> --style <s> --no-news --out debates/<ID>/fresh_<HHMM>.json` (HHMM = UTC now) and cite that file as the source; unsaved pulls are reported as unconfirmed.
> Write `debates/<ID>/r<N>_<bull|bear>.json` in your output format (Bull: `plan_numbers` required). Plain language for beginners.

**Rounds 1 and 2:** launch Bull and Bear in the same message (parallel). **Round 3 is sequential:** Bull first; then run the desk check (step b) on Bull's final plan; then Bear, told to read `r3_bull.json` and `desk_r3.json` so Bear answers the plan that is actually final.

After the debaters of round N:
a. **Validate:** `python tools/validate.py debates/<ID>/r<N>_bull.json debates/<ID>/r<N>_bear.json`. On exit code 2, re-run only the failing agent once, pasting the printed problems into its prompt. Still failing → stop and report.
b. **Desk check:** `python tools/desk.py analyze debates/<ID> --round N` → `desk_r<N>.json` (plan math, issues, Time Machine). (In Round 3 this runs between Bull and Bear.)
c. **Claim check:** `python tools/claims.py debates/<ID> --round N` → `claims_r<N>.json` (numbers that do not match the recorded data).
d. **Round Result:** one Agent, `subagent_type` `trade-judge`, `model: "sonnet"`:
   > Mode A: Round Result for Round N. Proposed trade **<TRADE>**. Debate folder `debates/<ID>/`. Referee numbers: `desk_r<N>.json`, `claims_r<N>.json`, `events.json`, `regime.json`. Write `debates/<ID>/r<N>_result.json` in your Mode A format.
   Then `python tools/validate.py debates/<ID>/r<N>_result.json` (re-run once on failure).
e. Render and republish. **In the cloud:** `git add debates docs && git commit -qm "<ID>: round N" && git push origin HEAD:main`.

## 3. The Judge's final conclusion
`python tools/calibration.py` first (refreshes the Judge's own track record), then one Agent, `subagent_type` `trade-judge` (opus):
> Mode B: Final Conclusion. Proposed trade **<TRADE>** (market `<m>`, style `<s>`). Debate folder `debates/<ID>/`. Read everything listed in your Mode B steps, including `claims_r1..3.json`, `optimizer.json`, `regime.json` and `docs/calibration.json`. Write `debates/<ID>/verdict.json` in your Mode B format, including `trade_plan_numbers` and all plain-language fields.
Validate with `python tools/validate.py debates/<ID>/verdict.json` (re-run once on failure).

## 4. Risk gate and ticket (code)
`python tools/desk.py gate debates/<ID>` → `desk_final.json`: fresh price, events refresh, costs, position size (cut by the volatility multiplier), every rule (holiday, volatility, claims, optimizer, reward-to-risk after costs, Time Machine, shorting, India forex, limits), the **final call** and, for a TAKE, the ticket.

## 5. Show the result
1. `python tools/render.py debates/<ID>`; republish the artifact. In the cloud: commit and push.
1b. **Alert (only for a final TAKE):** `python tools/notify.py "TAKE <TRADE>: <first ticket line> Page: <pages-url>/d/<ID>.html"`. If it printed `ALERT:` (no Telegram set up) and the PushNotification tool is available, send the same text with it.
2. Reply: proposed trade; market status, event guard, volatility; optimizer result; each round's result (plus any wrong numbers the claim checker caught); the final plan's Time Machine odds; the Judge's ruling and confidence; the risk gate with any block reasons; the **final call**; the ticket (TAKE) or what would change the Judge's mind (SKIP); page link; one line if capital is not set. End with: AI analysis, not financial advice; no order was placed.

Never place, simulate or route a real order. The user executes trades themselves.
