# Trade Debate Desk

A personal pre-trade desk for **crypto, US stocks, NSE and forex**. It does every step a careful trader does before pressing buy, and never presses buy itself.

**Core rule: the AI agents ARGUE, the code CALCULATES.** Every number your money depends on (reward-to-risk, stop size, costs, position size, odds, limits) comes from tested code in `tools/`, never from an AI.

## The pipeline for one proposed trade (e.g. `LONG ETH/USDT`)
```
1. Live snapshot ............ tools/market_data.py   price + indicators on 3 timeframes + news (Binance / Yahoo)
2. Event guard .............. tools/events.py        inflation, jobs, central banks (incl. RBI), earnings in the trade window
3. Round 1, 2, 3 ............ Bull Claude (FOR) ∥ Bear Claude (AGAINST), plain-language chat with cited proof
     after each round:
     • Desk calculator ...... tools/desk.py analyze  Bull's plan math (reward-to-risk, stop vs ATR, entry vs price)
     • Time Machine ......... tools/timemachine.py   10,000 replays from the asset's own last 60 days + real history
     • Round result ......... the Judge (Mode A)
4. Final conclusion ......... the Judge (Mode B): TAKE or SKIP
5. Risk gate + ticket ....... tools/desk.py gate     costs for your broker, position size, your limits → final call
6. Journal .................. tools/outcomes.py      later: did it hit the target or the stop? (TAKE and SKIP)
```

## Commands (open Claude Code in this folder)
| Command | What it does |
|---|---|
| `/trade-debate ETH long` · `/trade-debate RELIANCE long swing nse` · `/trade-debate EURUSD short entry 1.1230 stop 1.1260` | The full desk on one trade |
| `/trade-scan` · `/trade-scan crypto,nse 3 swing` | Journal update → scan open markets → filter out what your rules would block → full desk on the top picks |
| `/trade-check NVDA long entry 170.5 stop 167 target 176` | Code-only check of any plan in seconds (no debate) |
| `/trade-journal` | Track record: what really happened after every TAKE and SKIP |

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
If the cloud environment's network access is restricted, allow: `api.binance.com`, `data-api.binance.vision`, `fapi.binance.com`, `query1.finance.yahoo.com`, `feeds.finance.yahoo.com`, `news.google.com`, `api.alternative.me`, `economic-calendar.tradingview.com`, `nfs.faireconomy.media`, `api.nasdaq.com` (plus general web access for research).

## 24/7
Cloud routines run `/trade-scan` on a schedule; results are committed here and shown on the GitHub Pages dashboard (`docs/`).

## Credits
The Time Machine, risk gate and sizing ideas are adapted from the MIT-licensed [day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill), rebuilt for all four markets.

AI analysis of public data. Not financial advice. This tool never places orders.
