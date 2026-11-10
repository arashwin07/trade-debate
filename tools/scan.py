#!/usr/bin/env python3
"""Market scanner for auto mode: finds the most active movers in markets that are open now.

  crypto -> Binance 24h tickers (USDT pairs, liquid only)
  us     -> Yahoo Finance screeners (day gainers, day losers, most actives)
  nse    -> NIFTY 50 watchlist via Yahoo Finance (.NS)
  forex  -> major + INR pairs via Yahoo Finance

Usage: python tools/scan.py --markets crypto,us,nse,forex --top 3 [--include-closed] [--out file]
Output: JSON {scanned_utc, open_markets, candidates:[{symbol, market, change_pct, score, why}]}
"""
import argparse, json, math, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from market_data import get, binance, candles_yahoo  # noqa: E402

NIFTY50 = ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "BHARTIARTL", "ITC", "SBIN", "LT", "HINDUNILVR",
           "BAJFINANCE", "KOTAKBANK", "AXISBANK", "MARUTI", "SUNPHARMA", "HCLTECH", "M&M", "TITAN", "NTPC", "ULTRACEMCO",
           "ASIANPAINT", "ONGC", "POWERGRID", "TATASTEEL", "WIPRO", "ADANIENT", "ADANIPORTS", "JSWSTEEL", "COALINDIA",
           "BAJAJFINSV", "NESTLEIND", "GRASIM", "TECHM", "HINDALCO", "CIPLA", "DRREDDY", "BEL", "TRENT", "SBILIFE",
           "HDFCLIFE", "BRITANNIA", "EICHERMOT", "APOLLOHOSP", "TATACONSUM", "HEROMOTOCO", "SHRIRAMFIN", "INDUSINDBK",
           "BAJAJ-AUTO", "JIOFIN", "ETERNAL"]
FX = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURJPY", "GBPJPY", "EURGBP", "USDINR"]
STABLE = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "EUR", "BUSD", "USDE", "PYUSD", "AEUR", "XUSD", "USD1", "BFUSD"}


def forex_open():
    n = datetime.now(timezone.utc)
    return not (n.weekday() == 5 or (n.weekday() == 4 and n.hour >= 22) or (n.weekday() == 6 and n.hour < 22))


def session_open(sym):
    _, meta = candles_yahoo(sym, "1d", "1d")
    p = (meta.get("currentTradingPeriod") or {}).get("regular", {})
    return p.get("start", 0) <= time.time() <= p.get("end", 0)


def score(chg, vol_ratio=1.0):
    # bigger absolute move + more participation = more worth debating
    return round(abs(chg) * (1 + math.log10(max(vol_ratio, 0.1) + 1)), 3)


def scan_crypto(top):
    rows = binance("/api/v3/ticker/24hr")
    out = []
    for t in rows:
        s = t["symbol"]
        if not s.endswith("USDT"):
            continue
        base = s[:-4]
        if base in STABLE or base.endswith(("UP", "DOWN", "BULL", "BEAR")):
            continue
        qv = float(t["quoteVolume"])
        if qv < 100_000_000 or int(t.get("count", 0)) == 0:
            continue
        chg = float(t["priceChangePercent"])
        out.append({"symbol": base, "market": "crypto", "change_pct": round(chg, 2),
                    "score": score(chg, qv / 2e8),
                    "why": f"{chg:+.2f}% in 24h on ${qv/1e6:,.0f}M Binance volume"})
    return sorted(out, key=lambda x: -x["score"])[:top]


def scan_us(top):
    out, seen = [], set()
    for scr in ["day_gainers", "day_losers", "most_actives"]:
        try:
            d = get(f"https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds={scr}&count=15")
            quotes = d["finance"]["result"][0]["quotes"]
        except Exception:
            continue
        for q in quotes:
            s = q.get("symbol")
            cap = q.get("marketCap") or 0
            if not s or s in seen or cap < 2e9 or (q.get("regularMarketPrice") or 0) < 5:
                continue
            seen.add(s)
            chg = q.get("regularMarketChangePercent") or 0
            vr = (q.get("regularMarketVolume") or 0) / max(q.get("averageDailyVolume3Month") or 1, 1)
            out.append({"symbol": s, "market": "us", "change_pct": round(chg, 2), "score": score(chg, vr),
                        "why": f"{chg:+.2f}% today, volume {vr:.1f}x 3-month average ({scr.replace('_', ' ')})"})
    return sorted(out, key=lambda x: -x["score"])[:top]


def scan_watchlist(symbols, market, suffix, top):
    def one(s):
        try:
            cs, meta = candles_yahoo(s + suffix, "1d", "1mo")
            if len(cs) < 3:
                return None
            chg = (cs[-1]["c"] / cs[-2]["c"] - 1) * 100
            avgv = sum(c["v"] for c in cs[-21:-1]) / max(len(cs[-21:-1]), 1)
            vr = cs[-1]["v"] / avgv if avgv else 1.0
            why = f"{chg:+.2f}% today" + (f", volume {vr:.1f}x 20-day average" if avgv else "")
            return {"symbol": s, "market": market, "change_pct": round(chg, 2), "score": score(chg, vr), "why": why}
        except Exception:
            return None

    with ThreadPoolExecutor(10) as ex:
        res = [x for x in ex.map(one, symbols) if x]
    return sorted(res, key=lambda x: -x["score"])[:top]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--markets", default="crypto,us,nse,forex")
    ap.add_argument("--top", type=int, default=3, help="candidates kept per market before final ranking")
    ap.add_argument("--pick", type=int, default=3, help="final number of candidates returned")
    ap.add_argument("--include-closed", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    wanted = [m.strip() for m in a.markets.split(",") if m.strip()]

    status = {}
    for m in wanted:
        try:
            status[m] = True if m == "crypto" else forex_open() if m == "forex" else session_open("AAPL" if m == "us" else "^NSEI")
        except Exception:
            status[m] = False

    cands, notes = [], []
    for m in wanted:
        if not status[m] and not a.include_closed:
            notes.append(f"{m}: market closed, skipped")
            continue
        try:
            if m == "crypto":
                cands += scan_crypto(a.top)
            elif m == "us":
                cands += scan_us(a.top)
            elif m == "nse":
                cands += scan_watchlist(NIFTY50, "nse", ".NS", a.top)
            elif m == "forex":
                fx = scan_watchlist(FX, "forex", "=X", a.top)
                for c in fx:  # forex moves are small; scale so they compete fairly with stocks/crypto
                    c["score"] = round(c["score"] * 8, 3)
                cands += fx
        except Exception as e:
            notes.append(f"{m}: scan failed ({e})")

    # keep market diversity: best of each market first, then fill by score
    best = {}
    for c in sorted(cands, key=lambda x: -x["score"]):
        best.setdefault(c["market"], c)
    picked = sorted(best.values(), key=lambda x: -x["score"])[: a.pick]
    for c in sorted(cands, key=lambda x: -x["score"]):
        if len(picked) >= a.pick:
            break
        if c not in picked:
            picked.append(c)

    result = {"scanned_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "open_markets": [m for m in wanted if status[m]], "notes": notes,
              "candidates": picked, "all_ranked": sorted(cands, key=lambda x: -x["score"])}
    text = json.dumps(result, indent=2)
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        open(a.out, "w", encoding="utf-8").write(text)
        print(f"wrote {a.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
