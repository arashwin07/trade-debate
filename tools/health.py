#!/usr/bin/env python3
"""Health monitor (H): are all the free data sources working right now?

  python tools/health.py            # prints a table, writes docs/health.json; exit 1 if a CRITICAL source is down

Critical sources (the desk cannot work safely without them): prices for each market and the economic
calendar. Others degrade gracefully (the desk notes what is missing).
"""
import json, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

UA = {"User-Agent": "Mozilla/5.0 (trade-debate research script)", "Accept": "*/*"}
CHECKS = [
    # (name, critical, market, url, extra headers)
    ("Binance prices", True, "crypto", "https://data-api.binance.vision/api/v3/ticker/price?symbol=BTCUSDT", {}),
    ("Binance main API", False, "crypto", "https://api.binance.com/api/v3/ping", {}),
    ("Yahoo US stocks", True, "us", "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d&range=5d", {}),
    ("Yahoo NSE stocks", True, "nse", "https://query1.finance.yahoo.com/v8/finance/chart/RELIANCE.NS?interval=1d&range=5d", {}),
    ("Yahoo forex", True, "forex", "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?interval=1d&range=5d", {}),
    ("TradingView calendar", True, "all", None, {"Origin": "https://in.tradingview.com", "Referer": "https://in.tradingview.com/"}),
    ("ForexFactory calendar (backup)", False, "all", "https://nfs.faireconomy.media/ff_calendar_thisweek.json", {}),
    ("Nasdaq earnings", False, "us", None, {}),
    ("Fear & Greed index", False, "crypto", "https://api.alternative.me/fng/?limit=1", {}),
    ("Binance futures funding", False, "crypto", "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT", {}),
    ("Google News", False, "all", "https://news.google.com/rss/search?q=stock+market&hl=en-US&gl=US&ceid=US:en", {}),
    ("CNBC news", False, "us", "https://www.cnbc.com/id/100003114/device/rss/rss.html", {}),
    ("Economic Times news", False, "nse", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", {}),
    ("Cointelegraph news", False, "crypto", "https://cointelegraph.com/rss", {}),
    ("FXStreet news", False, "forex", "https://www.fxstreet.com/rss/news", {}),
]


def url_for(name):
    now = datetime.now(timezone.utc)
    if name == "TradingView calendar":
        a = now.strftime("%Y-%m-%dT00:00:00.000Z")
        return f"https://economic-calendar.tradingview.com/events?from={a}&to={a.replace('T00', 'T23')}&countries=US,IN"
    if name == "Nasdaq earnings":
        return f"https://api.nasdaq.com/api/calendar/earnings?date={now.strftime('%Y-%m-%d')}"


def check(item):
    name, critical, market, url, extra = item
    url = url or url_for(name)
    t0 = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={**UA, **extra}), timeout=15) as r:
            body = r.read(200000)
        ok = len(body) >= 2  # Binance ping legitimately answers "{}"
        note = f"{len(body)} bytes"
    except Exception as e:
        ok, note = False, f"{type(e).__name__}: {str(e)[:80]}"
    return {"name": name, "critical": critical, "market": market, "ok": ok, "ms": int((time.time() - t0) * 1000), "note": note}


def run():
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(check, CHECKS))
    crit_down = [r["name"] for r in res if r["critical"] and not r["ok"]]
    # the economic calendar is critical only if BOTH calendars are down
    if "TradingView calendar" in crit_down and next(r for r in res if r["name"].startswith("ForexFactory"))["ok"]:
        crit_down.remove("TradingView calendar")
    markets_down = sorted({r["market"] for r in res if r["critical"] and not r["ok"] and r["market"] != "all"})
    out = {"checked_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "status": "DOWN" if crit_down else "OK" if all(r["ok"] for r in res) else "DEGRADED",
           "critical_down": crit_down, "markets_down": markets_down, "sources": res}
    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    with open(os.path.join(ROOT, "docs", "health.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    out = run()
    for r in out["sources"]:
        print(f"{'OK  ' if r['ok'] else 'DOWN'} {'*' if r['critical'] else ' '} {r['name']:<32} {r['ms']:>5} ms  {'' if r['ok'] else r['note']}")
    print(f"\nOverall: {out['status']}" + (f" | critical down: {', '.join(out['critical_down'])} | do not trade markets: {', '.join(out['markets_down']) or 'all'}" if out["critical_down"] else ""))
    sys.exit(1 if out["critical_down"] else 0)


if __name__ == "__main__":
    main()
