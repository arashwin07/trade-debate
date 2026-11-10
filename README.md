# Trade Debate Desk

A personal pre-trade desk for **crypto, US stocks, NSE and forex**. It does every step a careful trader does before pressing buy, and never presses buy itself.

**Core rule: the AI agents ARGUE, the code CALCULATES.** Every number your money depends on (reward-to-risk, stop size, costs, position size, odds, limits) comes from tested code in `tools/`, never from an AI.

## The pipeline for one proposed trade (e.g. `LONG ETH/USDT`)
```
0. Health + budget .......... tools/health.py, budget.py   all data sources up? debates left today? (scan mode)
1. Live snapshot ............ tools/market_data.py   price + indicators on 3 timeframes (Binance / Yahoo)
2. Event guard .............. tools/events.py        inflation, jobs, central banks (incl. RBI), earnings in the window
3. Volatility + calendar .... tools/regime.py        how jumpy vs normal (cuts size), holidays, half days, VIX / India VIX
4. Levels ................... tools/levels.py        real floors/ceilings: yesterday H/L, pivots, VWAP, opening range, turning points
5. News ..................... tools/news.py          fresh, timestamped, de-duplicated, trust-ranked headlines
6. Plan optimizer ........... tools/optimizer.py     best plan from real levels that passes the rules + Time Machine, or "none"
7. Round 1, 2 (parallel), Round 3 (Bull, then Bear answers Bull's FINAL plan)
     after each agent file:   tools/validate.py      guardrails: format, sides, sane numbers (re-run the agent if broken)
     after each round:        tools/desk.py analyze  plan math + Time Machine (10,000 replays + real history)
                              tools/claims.py        every cited data number checked against the recorded data
                              the Judge (Mode A)     round result
8. Final conclusion ......... the Judge (Mode B), reading its own track record (tools/calibration.py)
9. Risk gate + ticket ....... tools/desk.py gate     costs, size (x volatility), all rules → final call + ticket
10. Journal ................. tools/outcomes.py      what really happened (TAKE and SKIP), feeds calibration
Every tool appends to debates/<id>/audit.log.
```

## Commands (open Claude Code in this folder)
| Command | What it does |
|---|---|
| `/trade-debate ETH long` · `/trade-debate RELIANCE long swing nse` · `/trade-debate EURUSD short entry 1.1230 stop 1.1260` | The full desk on one trade |
| `/trade-scan` · `/trade-scan crypto,nse 3 swing` | Journal update → scan open markets → filter out what your rules would block → full desk on the top picks |
| `/trade-check NVDA long entry 170.5 stop 167 target 176` | Code-only check of any plan in seconds (no debate) |
| `/trade-journal` | Track record: what really happened after every TAKE and SKIP |
| `/trade-brief nse` · `/trade-brief us` | Morning brief before the bell: mood, events, overnight moves, watchlist, track record |
| `/trade-settings` | Show or change capital, risk limits, shorting rules, costs, AI usage limits (validated) |
| `/trade-review` | Weekly lessons: calibration, agent quality, practice account, backtests → suggested changes |

## More tools
`tools/context.py` (market tailwind/headwind) · `fundamentals.py` (growth, margins, debt, valuation; coin supply) · `derivatives.py` (crypto open interest, funding, crowd) ·
`watch.py` (watchlist + retake watcher) · `paper.py` (practice account) · `backtest.py` (code backtest of the desk's rules) · `quality.py` (agent accuracy) ·
`notify.py` (Telegram if `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` are set, otherwise Claude's push notification) · `settings.py` · `.github/workflows/tests.yml` (tests on every push, nightly data-source check).
Your watchlist and notes: `config/watchlist.json`.

## Your settings: `config/desk.json`
- `accounts.<market>.capital` (**set these**; until then no position size is calculated), currency, broker
- `risk`: risk per trade %, daily limits, max trades per day, minimum reward-to-risk after costs (1.5), minimum stop size (1x ATR), shorting allowed per market
- `costs`: Binance fees, NSE intraday/delivery charges (brokerage, STT, exchange, SEBI, stamp duty, GST, DP), US fees, forex spread. Typical published rates; check them against your broker.
- `owner.residence: IN`: forex is limited to the pairs Indian residents may legally trade (INR pairs plus EUR/USD, GBP/USD, USD/JPY, exchange-traded on NSE/BSE only).

## Tests
`python -m unittest discover -s tests -v`: plan parsing, plan math, NSE/crypto/forex costs, position sizing (300 random cases: the loss at the stop never exceeds the budget), every risk-gate rule, Time Machine fairness and determinism, outcome tracking.

## Free data sources
| Market | Prices | Events | News |
|---|---|---|---|
| Crypto | Binance public API (+ order book, funding, Fear & Greed) | TradingView / ForexFactory (USD macro) | Google News + agents' research |
| US stocks | Yahoo Finance | macro + Nasdaq earnings calendar | Google News, Yahoo RSS + research |
| NSE India | Yahoo Finance (.NS) | macro incl. India (RBI, CPI) | Google News India + research |
| Forex | Yahoo Finance (=X) | macro for both currencies | Google News + research |

Yahoo data can be delayed up to 15 minutes on some exchanges; every page shows the data time.

## Cloud network allowlist
If the cloud environment's network access is restricted, allow: `api.binance.com`, `data-api.binance.vision`, `fapi.binance.com`, `query1.finance.yahoo.com`, `feeds.finance.yahoo.com`, `news.google.com`, `api.alternative.me`, `economic-calendar.tradingview.com`, `nfs.faireconomy.media`, `api.nasdaq.com`, and the news feeds (`www.cnbc.com`, `feeds.content.dowjones.io`, `economictimes.indiatimes.com`, `www.livemint.com`, `www.business-standard.com`, `cointelegraph.com`, `www.theblock.co`, `www.coindesk.com`, `www.fxstreet.com`) plus general web access for research.

## 24/7
Cloud routines run `/trade-scan` on a schedule; results are committed here and shown on the GitHub Pages dashboard (`docs/`).

## Credits
The Time Machine, risk gate and sizing ideas are adapted from the MIT-licensed [day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill), rebuilt for all four markets.

AI analysis of public data. Not financial advice. This tool never places orders.
