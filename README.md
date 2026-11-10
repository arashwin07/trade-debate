# Trade Debate Desk

Three Claude agents debate a **proposed trade** (asset + direction, e.g. `LONG BTC/USDT`, `SHORT EURUSD`) on live market data:

| Agent | File | Role |
|---|---|---|
| **Bull Claude** | `.claude/agents/bull-claude.md` | Always argues **FOR** taking the trade, with cited live evidence. Never switches sides. |
| **Bear Claude** | `.claude/agents/bear-claude.md` | Always argues **AGAINST** taking the trade, with cited live evidence. Never switches sides. |
| **The Judge** | `.claude/agents/trade-judge.md` | Fact-checks both, scores them, decides **TAKE** or **SKIP**. |

## Workflow
```
snapshot (live data + news) ─► R1 Opening  (Bull ∥ Bear)
                              ─► R2 Rebuttal (each attacks the other's R1)
                              ─► R3 Closing  (each answers the other's R2)
                              ─► Judge: re-checks live price, fact-checks claims, scores, rules
                              ─► debate page (debates/<id>/debate.html) + dashboard (docs/index.html)
```

## Commands (open Claude Code in this folder)
- `/trade-debate BTC long` · `/trade-debate AAPL short swing` · `/trade-debate RELIANCE long intraday nse` · `/trade-debate EURUSD short entry 1.1230 stop 1.1260`
- Direction defaults to `long` if you leave it out.
- `/trade-scan` (finds top movers in open markets, proposes a trade in the direction of the move, debates each) · `/trade-scan crypto,nse 3 swing`

## Adding features
The project is split so new pieces slot in without rewrites:
- `tools/` holds data scripts (add a new market or data source here),
- `.claude/agents/` holds the debaters and the Judge (add a new specialist agent here),
- `.claude/skills/` holds the workflows (add a new command here),
- `tools/render.py` turns each `debates/<id>/` folder into the viewer page.

## Free data sources
| Market | Prices and indicators | News |
|---|---|---|
| Crypto | Binance public API (+ order book, funding, Fear & Greed) | Google News, agents' web research (CoinDesk, The Block…) |
| US stocks | Yahoo Finance | Google News, Yahoo Finance RSS, Reuters, CNBC… |
| NSE India | Yahoo Finance (.NS) | Google News India, Moneycontrol, Economic Times… |
| Forex | Yahoo Finance (=X) | Google News, FXStreet, Forex Factory calendar… |

Yahoo data can be delayed up to 15 minutes on some exchanges; every page shows the data timestamp.

## 24/7
Push this folder to a GitHub repo, enable GitHub Pages on `/docs`, and create a Claude Code cloud routine that runs `/trade-scan` on a schedule. Results are committed to the repo and visible on the Pages site from any device, with your PC off.

AI analysis of public data. Not financial advice. This workflow never places orders.
