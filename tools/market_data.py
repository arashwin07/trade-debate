#!/usr/bin/env python3
"""Live market evidence snapshot for the Bull / Bear / Judge trade debate.

Free public data only, one platform per market:
  crypto -> Binance public REST (api.binance.com, falls back to data-api.binance.vision)
  us     -> Yahoo Finance chart API (NASDAQ / NYSE)
  nse    -> Yahoo Finance chart API (.NS symbols, National Stock Exchange of India)
  forex  -> Yahoo Finance chart API (=X pairs)
News (all markets): Google News RSS + Yahoo Finance RSS (+ crypto Fear & Greed index).

Usage:
  python tools/market_data.py BTC              --style intraday --out debates/x/snapshot.json
  python tools/market_data.py RELIANCE --market nse --style swing
  python tools/market_data.py EURUSD   --market forex
Stdlib only, so it runs anywhere (local PC or cloud).
"""
import argparse, json, math, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (trade-debate research script)"}
BINANCE_HOSTS = ["https://api.binance.com", "https://data-api.binance.vision"]
CRYPTO_HINTS = {"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "DOT", "LINK", "MATIC", "POL",
                "LTC", "TRX", "SHIB", "TON", "SUI", "APT", "ARB", "OP", "NEAR", "PEPE", "ATOM", "UNI", "BCH"}
FX_CODES = {"USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF", "INR", "CNY", "SGD", "HKD", "SEK", "NOK", "MXN", "ZAR"}


def now_utc():
    return datetime.now(timezone.utc)


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get(url, raw=False, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if raw else json.loads(data)


# ---------------------------------------------------------------- symbol routing
def detect(symbol, market):
    s = symbol.strip().upper()
    if market == "auto":
        if s.endswith(".NS") or s.endswith(".BO"):
            market = "nse"
        elif s.endswith("=X") or (len(s) == 6 and s[:3] in FX_CODES and s[3:] in FX_CODES):
            market = "forex"
        elif s.endswith("USDT") or s.endswith("-USD") or s in CRYPTO_HINTS:
            market = "crypto"
        else:
            market = "us"
    if market == "crypto":
        base = s.replace("-USD", "").replace("USDT", "").replace("/", "")
        return market, base + "USDT", base + "/USDT"
    if market == "nse":
        sym = s if s.endswith((".NS", ".BO")) else s + ".NS"
        return market, sym, sym.split(".")[0]
    if market == "forex":
        pair = s.replace("=X", "").replace("/", "")
        return market, pair + "=X", pair[:3] + "/" + pair[3:]
    return "us", s, s


# ---------------------------------------------------------------- candles
def binance(path):
    last = None
    for host in BINANCE_HOSTS:
        try:
            return get(host + path)
        except Exception as e:  # geo-block or outage -> next host
            last = e
    raise last


def candles_binance(sym, interval, limit):
    rows = binance(f"/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}")
    return [dict(t=r[0] // 1000, o=float(r[1]), h=float(r[2]), l=float(r[3]), c=float(r[4]), v=float(r[5])) for r in rows]


def candles_yahoo(sym, interval, rng):
    d = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?interval={interval}&range={rng}&includePrePost=false")
    res = d["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(res.get("timestamp") or []):
        c = q["close"][i]
        if c is None:
            continue
        out.append(dict(t=t, o=q["open"][i] or c, h=q["high"][i] or c, l=q["low"][i] or c, c=c, v=q["volume"][i] or 0))
    return out, res["meta"]


# ---------------------------------------------------------------- indicators
def sma(xs, n):
    return sum(xs[-n:]) / n if len(xs) >= n else None


def ema_series(xs, n):
    if len(xs) < n:
        return []
    k, e = 2 / (n + 1), sum(xs[:n]) / n
    out = [e]
    for x in xs[n:]:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def rsi(xs, n=14):
    if len(xs) <= n:
        return None
    gains = [max(xs[i] - xs[i - 1], 0) for i in range(1, len(xs))]
    losses = [max(xs[i - 1] - xs[i], 0) for i in range(1, len(xs))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        ag, al = (ag * (n - 1) + g) / n, (al * (n - 1) + l) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def atr(cs, n=14):
    if len(cs) <= n:
        return None
    trs = [max(c["h"] - c["l"], abs(c["h"] - p["c"]), abs(c["l"] - p["c"])) for p, c in zip(cs, cs[1:])]
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


def macd(xs):
    e12, e26 = ema_series(xs, 12), ema_series(xs, 26)
    if not e26:
        return None
    line = [a - b for a, b in zip(e12[-len(e26):], e26)]
    sig = ema_series(line, 9)
    if not sig:
        return None
    return dict(macd=line[-1], signal=sig[-1], histogram=line[-1] - sig[-1],
                prev_histogram=(line[-2] - sig[-2]) if len(sig) > 1 else None)


def r(x, nd=None):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    if nd is None:
        ax = abs(x)
        nd = 2 if ax >= 100 else 4 if ax >= 1 else 6
    return round(x, nd)


def analyse(cs, label, session_vwap=False):
    if len(cs) < 30:
        return {"timeframe": label, "error": f"only {len(cs)} candles"}
    closes = [c["c"] for c in cs]
    last = cs[-1]
    e9, e21 = ema_series(closes, 9), ema_series(closes, 21)
    s20, s50, s200 = sma(closes, 20), sma(closes, 50), sma(closes, 200)
    sd20 = (sum((x - s20) ** 2 for x in closes[-20:]) / 20) ** 0.5
    vols = [c["v"] for c in cs]
    vavg = sma(vols[:-1], 20)
    look = cs[-50:]
    out = {
        "timeframe": label,
        "candles": len(cs),
        "last_candle_utc": iso(last["t"]),
        "close": r(last["c"]),
        "ema9": r(e9[-1]) if e9 else None,
        "ema21": r(e21[-1]) if e21 else None,
        "sma20": r(s20), "sma50": r(s50), "sma200": r(s200),
        "rsi14": r(rsi(closes), 1),
        "macd": {k: r(v) for k, v in (macd(closes) or {}).items()},
        "atr14": r(atr(cs)),
        "bollinger": {"upper": r(s20 + 2 * sd20), "lower": r(s20 - 2 * sd20)},
        "volume_vs_20avg": r(vols[-1] / vavg, 2) if vavg else None,
        "recent_high_50": r(max(c["h"] for c in look)),
        "recent_low_50": r(min(c["l"] for c in look)),
        "change_over_window_pct": r((closes[-1] / closes[0] - 1) * 100, 2),
    }
    trend = []
    if e9 and e21:
        trend.append("EMA9 above EMA21" if e9[-1] > e21[-1] else "EMA9 below EMA21")
    if s50:
        trend.append("price above SMA50" if last["c"] > s50 else "price below SMA50")
    if s200:
        trend.append("price above SMA200" if last["c"] > s200 else "price below SMA200")
    out["trend_facts"] = trend
    if session_vwap:
        day = datetime.fromtimestamp(last["t"], timezone.utc).date()
        sess = [c for c in cs if datetime.fromtimestamp(c["t"], timezone.utc).date() == day]
        pv = sum((c["h"] + c["l"] + c["c"]) / 3 * c["v"] for c in sess)
        vv = sum(c["v"] for c in sess)
        out["session_vwap_utc_day"] = r(pv / vv) if vv else None
    return out


# ---------------------------------------------------------------- news
def rss(url, source_hint, limit=10):
    try:
        root = ET.fromstring(get(url, raw=True))
    except Exception as e:
        return [{"error": f"{source_hint}: {e}"}]
    items = []
    for it in root.iter("item"):
        src = it.find("source")
        items.append({
            "title": (it.findtext("title") or "").strip(),
            "source": (src.text if src is not None else source_hint),
            "published": it.findtext("pubDate"),
            "url": it.findtext("link"),
        })
        if len(items) >= limit:
            break
    return items


def news(market, display, yahoo_sym, name=None):
    q = {
        "crypto": f"{display.split('/')[0]} crypto price",
        "nse": f"{name or display} share NSE",
        "forex": f"{display} forex",
        "us": f"{name or display} stock",
    }[market]
    feeds = [rss("https://news.google.com/rss/search?q=" + urllib.parse.quote(q + " when:2d") + "&hl=en-US&gl=US&ceid=US:en", "Google News")]
    if market == "nse":
        feeds.append(rss("https://news.google.com/rss/search?q=" + urllib.parse.quote(q + " when:2d") + "&hl=en-IN&gl=IN&ceid=IN:en", "Google News India"))
    if market != "crypto":
        feeds.append(rss(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={urllib.parse.quote(yahoo_sym)}&region=US&lang=en-US", "Yahoo Finance"))
    seen, merged = set(), []
    for f in feeds:
        for it in f:
            key = (it.get("title") or it.get("error", ""))[:80].lower()
            if key and key not in seen:
                seen.add(key)
                merged.append(it)
    return merged[:18]


# ---------------------------------------------------------------- per market
def snapshot_crypto(sym, display, style):
    plan = [("5m", 300, True), ("15m", 300, False), ("1h", 300, False)] if style == "intraday" else [("1h", 300, False), ("4h", 300, False), ("1d", 300, False)]
    with ThreadPoolExecutor(4) as ex:
        tfs = list(ex.map(lambda p: analyse(candles_binance(sym, p[0], p[1]), p[0], p[2]), plan))
        t24 = ex.submit(binance, f"/api/v3/ticker/24hr?symbol={sym}")
        book = ex.submit(binance, f"/api/v3/depth?symbol={sym}&limit=100")
        fng = ex.submit(lambda: get("https://api.alternative.me/fng/?limit=2"))
        fund = ex.submit(lambda: get(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={sym}"))
    t = t24.result()
    out = {
        "price": r(float(t["lastPrice"])),
        "change_24h_pct": r(float(t["priceChangePercent"]), 2),
        "high_24h": r(float(t["highPrice"])), "low_24h": r(float(t["lowPrice"])),
        "quote_volume_24h_usdt": round(float(t["quoteVolume"])),
        "market_status": "OPEN (crypto trades 24/7)",
        "data_source": "Binance public API",
        "timeframes": tfs,
    }
    try:
        b = book.result()
        bid = sum(float(p) * float(q) for p, q in b["bids"])
        ask = sum(float(p) * float(q) for p, q in b["asks"])
        out["order_book_top100"] = {"bid_value_usdt": round(bid), "ask_value_usdt": round(ask),
                                    "bid_ask_ratio": r(bid / ask, 2) if ask else None,
                                    "spread": r(float(b["asks"][0][0]) - float(b["bids"][0][0]))}
    except Exception as e:
        out["order_book_top100"] = {"error": str(e)}
    try:
        f = fng.result()["data"]
        out["fear_greed_index"] = {"value": int(f[0]["value"]), "label": f[0]["value_classification"],
                                   "previous": int(f[1]["value"]), "source": "alternative.me"}
    except Exception as e:
        out["fear_greed_index"] = {"error": str(e)}
    try:
        f = fund.result()
        out["perp_funding_rate_pct"] = r(float(f["lastFundingRate"]) * 100, 4)
    except Exception:
        out["perp_funding_rate_pct"] = "unavailable (Binance futures API blocked from this location)"
    return out


def tradingview_quote(market, sym):
    """Second price source for US/NSE: TradingView's public scanner. It also says how delayed its own feed is."""
    base = sym.upper().split(".")[0]
    tickers = [f"NSE:{base}"] if market == "nse" else [f"NASDAQ:{base}", f"NYSE:{base}", f"AMEX:{base}"]
    body = json.dumps({"symbols": {"tickers": tickers}, "columns": ["close", "update_mode", "last_bar_update_time"]}).encode()
    req = urllib.request.Request(f"https://scanner.tradingview.com/{'india' if market == 'nse' else 'america'}/scan", data=body,
                                 headers={**UA, "Content-Type": "application/json", "Origin": "https://in.tradingview.com", "Referer": "https://in.tradingview.com/"})
    with urllib.request.urlopen(req, timeout=15) as f:
        rows = json.loads(f.read()).get("data") or []
    if not rows:
        return None
    close, mode, upd = rows[0]["d"]
    delay = None
    if isinstance(mode, str) and mode.startswith("delayed_streaming_"):
        delay = int(mode.rsplit("_", 1)[1]) // 60
    return {"source": "TradingView scanner", "ticker": rows[0]["s"], "price": close, "feed": mode,
            "feed_delay_minutes": delay if delay is not None else (0 if mode == "streaming" else None),
            "last_update_utc": iso(upd) if upd else None}


def price_check(market, sym, price, is_open, last_trade_ts):
    """How old is our price, and does a second source agree? Measured, not assumed."""
    out = {"data_delay_minutes": round((time.time() - last_trade_ts) / 60, 1) if (is_open and last_trade_ts) else None,
           "delay_note": None if is_open else "Market closed: delay can only be measured while the market is open."}
    if market not in ("us", "nse"):
        return out
    try:
        tv = tradingview_quote(market, sym)
    except Exception as e:
        tv, out["second_source_error"] = None, type(e).__name__
    if tv:
        out["second_source"] = tv
        if price and tv.get("price"):
            out["second_source_diff_pct"] = round(abs(price / tv["price"] - 1) * 100, 3)
    return out


def snapshot_yahoo(market, sym, style):
    plan = [("5m", "5d", True), ("15m", "1mo", False), ("1h", "3mo", False)] if style == "intraday" else [("1h", "3mo", False), ("1d", "1y", False), ("1wk", "5y", False)]

    def run(p):
        cs, meta = candles_yahoo(sym, p[0], p[1])
        return analyse(cs, p[0], p[2]), meta

    with ThreadPoolExecutor(3) as ex:
        res = list(ex.map(run, plan))
        daily = ex.submit(candles_yahoo, sym, "1d", "1mo").result()
    tfs = [x[0] for x in res]
    meta = res[0][1]
    dcs = daily[0]
    prev_close = dcs[-2]["c"] if len(dcs) > 1 else meta.get("chartPreviousClose")
    price = meta.get("regularMarketPrice")
    period = (meta.get("currentTradingPeriod") or {}).get("regular", {})
    now = time.time()
    if market == "forex":
        wd, hr = now_utc().weekday(), now_utc().hour
        is_open = not (wd == 5 or (wd == 4 and hr >= 22) or (wd == 6 and hr < 22))
        status = "OPEN (forex 24/5)" if is_open else "CLOSED (forex weekend)"
    else:
        is_open = period.get("start", 0) <= now <= period.get("end", 0)
        status = ("OPEN" if is_open else "CLOSED") + f" ({meta.get('exchangeName')}, regular session {iso(period['start']) if period.get('start') else '?'} to {iso(period['end']) if period.get('end') else '?'})"
    return {
        "name": meta.get("longName") or meta.get("shortName"),
        "currency": meta.get("currency"),
        "price": r(price),
        "previous_close": r(prev_close),
        "change_today_pct": r((price / prev_close - 1) * 100, 2) if price and prev_close else None,
        "day_high": r(meta.get("regularMarketDayHigh")), "day_low": r(meta.get("regularMarketDayLow")),
        "day_volume": meta.get("regularMarketVolume"),
        "week52_high": r(meta.get("fiftyTwoWeekHigh")), "week52_low": r(meta.get("fiftyTwoWeekLow")),
        "last_trade_utc": iso(meta["regularMarketTime"]) if meta.get("regularMarketTime") else None,
        "market_status": status,
        "data_source": "Yahoo Finance chart API" + (" (NSE India)" if market == "nse" else ""),
        "note": "Yahoo data for some exchanges can be delayed up to 15 min; see price_check.data_delay_minutes.",
        "price_check": price_check(market, sym, price, is_open and market != "forex", meta.get("regularMarketTime")),
        "timeframes": tfs,
    }


def build(symbol, market="auto", style="intraday", with_news=True):
    market, sym, display = detect(symbol, market)
    body = snapshot_crypto(sym, display, style) if market == "crypto" else snapshot_yahoo(market, sym, style)
    snap = {
        "symbol": display, "data_symbol": sym, "market": market, "style": style,
        "snapshot_utc": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
        **body,
    }
    if with_news:
        snap["news"] = news(market, display, sym if market != "crypto" else display, body.get("name"))
    return snap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--market", default="auto", choices=["auto", "crypto", "us", "nse", "forex"])
    ap.add_argument("--style", default="intraday", choices=["intraday", "swing"])
    ap.add_argument("--no-news", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    try:
        snap = build(a.symbol, a.market, a.style, not a.no_news)
    except Exception as e:
        print(json.dumps({"error": f"{type(e).__name__}: {e}", "symbol": a.symbol}), file=sys.stderr)
        sys.exit(1)
    text = json.dumps(snap, indent=2, ensure_ascii=False)
    if a.out:
        import os
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"wrote {a.out}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)


if __name__ == "__main__":
    main()
