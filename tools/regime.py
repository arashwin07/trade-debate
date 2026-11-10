#!/usr/bin/env python3
"""Volatility regime + market calendar (V).

  python tools/regime.py ETH --market crypto --style intraday --out debates/<id>/regime.json

Volatility: today's ATR as a share of price, compared with its typical (median) value over the last
~60 days (intraday: 1h bars; swing: daily bars). Ratio >= high_ratio -> HIGH (position size x0.5),
>= extreme_ratio -> EXTREME (x0.25). Also reads the fear gauges: VIX (US) and India VIX (NSE).
Calendar: holiday / weekend / half-day detection from the exchange's own trading period (Yahoo), so a
trading holiday is caught without a hand-typed holiday list.
"""
import argparse, json, os, statistics, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import market_data as md  # noqa: E402
from audit import audit  # noqa: E402


def atr_series(cs, n=14):
    trs = [max(c["h"] - c["l"], abs(c["h"] - p["c"]), abs(c["l"] - p["c"])) for p, c in zip(cs, cs[1:])]
    out, a = [], None
    for i, tr in enumerate(trs):
        a = tr if a is None else (a * (n - 1) + tr) / n
        if i >= n:
            out.append(a / cs[i + 1]["c"])
    return out


def fear_gauge(sym):
    try:
        _, meta = md.candles_yahoo(sym, "1d", "5d")
        return meta.get("regularMarketPrice")
    except Exception:
        return None


def calendar_status(market, data_sym):
    """OPEN / CLOSED_WEEKEND / CLOSED_HOLIDAY / CLOSED (outside hours) for stock markets, from Yahoo's trading period."""
    if market == "crypto":
        return {"status": "OPEN", "plain": "Crypto trades 24/7."}
    now = datetime.now(timezone.utc)
    if market == "forex":
        wd = now.weekday()
        closed = wd == 5 or (wd == 4 and now.hour >= 22) or (wd == 6 and now.hour < 22)
        return {"status": "CLOSED_WEEKEND" if closed else "OPEN", "plain": "Forex is closed for the weekend." if closed else "Forex trades 24 hours on weekdays."}
    _, meta = md.candles_yahoo(data_sym, "1d", "5d")
    per = (meta.get("currentTradingPeriod") or {}).get("regular", {})
    off = int(meta.get("gmtoffset") or 0)
    start, end = per.get("start", 0), per.get("end", 0)
    local_now = datetime.fromtimestamp(now.timestamp() + off, timezone.utc)
    local_start = datetime.fromtimestamp(start + off, timezone.utc)
    hours = (end - start) / 3600 if end > start else 0
    if start <= now.timestamp() <= end:
        st = "OPEN"
        plain = "The market is open." + (f" Short session today ({hours:.1f} hours): it closes early." if 0 < hours < 5.5 else "")
    elif local_now.weekday() >= 5:
        st, plain = "CLOSED_WEEKEND", "The market is closed for the weekend."
    elif local_start.date() != local_now.date() and now.timestamp() < start:
        st, plain = "CLOSED_HOLIDAY", f"No trading session today: likely an exchange holiday. Next session opens {local_start.strftime('%a %d %b %H:%M')} local time."
    else:
        st, plain = "CLOSED", "The market is outside its trading hours right now."
    return {"status": st, "plain": plain, "session_hours": round(hours, 2), "half_day": 0 < hours < 5.5}


def compute(symbol, market="auto", style="intraday"):
    cfg = json.load(open(os.path.join(ROOT, "config", "desk.json"), encoding="utf-8"))["volatility"]
    market, sym, display = md.detect(symbol, market)
    if market == "crypto":
        cs = md.candles_binance(sym, "1d" if style == "swing" else "1h", 400 if style == "swing" else 1000)
    else:
        cs, _ = md.candles_yahoo(sym, "1d" if style == "swing" else "1h", "2y" if style == "swing" else "3mo")
    s = atr_series(cs)
    now_atr, typical = s[-1], statistics.median(s[-(250 if style == "swing" else 60 * 7):])
    ratio = now_atr / typical if typical else 1.0
    level = "EXTREME" if ratio >= cfg["extreme_ratio"] else "HIGH" if ratio >= cfg["high_ratio"] else "LOW" if ratio <= 0.6 else "NORMAL"
    mult = {"EXTREME": cfg["size_multiplier_extreme"], "HIGH": cfg["size_multiplier_high"]}.get(level, 1.0)
    gauges = {}
    if market in ("us", "crypto"):
        gauges["VIX"] = fear_gauge("^VIX")
    if market == "nse":
        gauges["India VIX"] = fear_gauge("^INDIAVIX")
    fear = [k for k, v in gauges.items() if v and v >= (cfg["india_vix_high"] if k == "India VIX" else cfg["vix_high"])]
    plain = {"EXTREME": f"This market is moving about {ratio:.1f}x more than usual. Stops get hit by noise; position size cut to a quarter.",
             "HIGH": f"This market is moving about {ratio:.1f}x more than usual. Position size cut in half.",
             "LOW": f"This market is unusually quiet ({ratio:.1f}x its normal movement). Targets may take longer to reach.",
             "NORMAL": f"Normal movement ({ratio:.1f}x its usual range)."}[level]
    if fear:
        plain += " Fear gauge high: " + ", ".join(f"{k} {gauges[k]:.1f}" for k in fear) + "."
    return {"computed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "symbol": display, "market": market, "style": style,
            "atr_pct_now": round(now_atr * 100, 3), "atr_pct_typical": round(typical * 100, 3), "ratio": round(ratio, 2), "level": level,
            "size_multiplier": mult, "fear_gauges": gauges, "fear_high": fear, "calendar": calendar_status(market, sym), "plain": plain}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--market", default="auto")
    ap.add_argument("--style", default="intraday", choices=["intraday", "swing"])
    ap.add_argument("--out")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    res = compute(a.symbol, a.market, a.style)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
        audit(os.path.dirname(os.path.abspath(a.out)), "regime", f"{res['level']} x{res['size_multiplier']} | {res['calendar']['status']}")
        print(f"wrote {a.out}: {res['level']} (x{res['size_multiplier']}) | {res['calendar']['plain']} | {res['plain']}")
    else:
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
