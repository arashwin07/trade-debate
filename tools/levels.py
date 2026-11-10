#!/usr/bin/env python3
"""Levels engine (L): the real floors and ceilings around the price, computed by code.

  python tools/levels.py ETH --market crypto --style intraday --out debates/<id>/levels.json

Levels (each with distance from the price in % and in ATR, and how many times price reacted there):
  - previous day high / low / close, today's open, today's high / low
  - opening range (first 15 minutes) for US and NSE stocks
  - classic floor pivots from the previous day (P, R1, R2, S1, S2)
  - session VWAP (today's average traded price)
  - swing highs and lows (turning points) on the 1h chart (intraday) or daily chart (swing), clustered
  - 52-week high / low, and round numbers near the price
"""
import argparse, json, math, os, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import market_data as md  # noqa: E402
from audit import audit  # noqa: E402


def fetch(market, sym, interval, n_or_range):
    if market == "crypto":
        return md.candles_binance(sym, interval, n_or_range), 0
    cs, meta = md.candles_yahoo(sym, interval, n_or_range)
    return cs, (0 if market == "forex" else int(meta.get("gmtoffset") or 0))


def day_of(t, off):
    return (t + off) // 86400


def swings(cs, k=3):
    """Fractal turning points: a high higher than k bars each side (or a low lower)."""
    hi, lo = [], []
    for i in range(k, len(cs) - k):
        win = cs[i - k:i + k + 1]
        if cs[i]["h"] == max(b["h"] for b in win):
            hi.append(cs[i]["h"])
        if cs[i]["l"] == min(b["l"] for b in win):
            lo.append(cs[i]["l"])
    return hi, lo


def cluster(prices, tol):
    """Merge prices closer than tol; strength = how many turning points landed there."""
    out = []
    for p in sorted(prices):
        if out and p - out[-1]["prices"][-1] <= tol:
            out[-1]["prices"].append(p)
        else:
            out.append({"prices": [p]})
    return [{"price": sum(c["prices"]) / len(c["prices"]), "touches": len(c["prices"])} for c in out]


def round_step(price):
    mag = 10 ** math.floor(math.log10(price))
    return mag / 2 if price / mag < 2.5 else mag


def compute(symbol, market="auto", style="intraday"):
    market, sym, display = md.detect(symbol, market)
    snap = md.build(display, market, style, with_news=False)
    price = snap["price"]
    tfs = {t["timeframe"]: t for t in snap.get("timeframes", []) if not t.get("error")}
    atr = (tfs.get("1d") if style == "swing" else tfs.get("1h") or {}).get("atr14") or next(iter(tfs.values()))["atr14"]
    lv = []

    def add(p, kind, label, touches=1):
        if p and p > 0:
            lv.append({"price": round(p, 6), "kind": kind, "label": label, "touches": touches})

    daily, off = fetch(market, sym, "1d", 400 if market == "crypto" else "2y")
    today = day_of(datetime.now(timezone.utc).timestamp(), off)
    closed = [b for b in daily if day_of(b["t"], off) < today]
    if closed:
        pd = closed[-1]
        add(pd["h"], "prev_day", "Yesterday's high")
        add(pd["l"], "prev_day", "Yesterday's low")
        add(pd["c"], "prev_day", "Yesterday's close")
        P = (pd["h"] + pd["l"] + pd["c"]) / 3
        rng = pd["h"] - pd["l"]
        add(P, "pivot", "Pivot point")
        add(2 * P - pd["l"], "pivot", "Pivot R1 (first ceiling)")
        add(P + rng, "pivot", "Pivot R2 (second ceiling)")
        add(2 * P - pd["h"], "pivot", "Pivot S1 (first floor)")
        add(P - rng, "pivot", "Pivot S2 (second floor)")
    yr = daily[-252:] if market != "crypto" else daily[-365:]
    if yr:
        add(max(b["h"] for b in yr), "52w", "52-week high")
        add(min(b["l"] for b in yr), "52w", "52-week low")
    if style == "intraday":
        m5, off5 = fetch(market, sym, "5m", 288 if market == "crypto" else "5d")
        tday = [b for b in m5 if day_of(b["t"], off5) == day_of(m5[-1]["t"], off5)] if m5 else []
        if tday:
            add(tday[0]["o"], "today", "Today's open")
            add(max(b["h"] for b in tday), "today", "Today's high so far")
            add(min(b["l"] for b in tday), "today", "Today's low so far")
            if market in ("us", "nse") and len(tday) >= 3:
                add(max(b["h"] for b in tday[:3]), "opening_range", "Opening range high (first 15 min)")
                add(min(b["l"] for b in tday[:3]), "opening_range", "Opening range low (first 15 min)")
        vw = (tfs.get("5m") or {}).get("session_vwap_utc_day")
        add(vw, "vwap", "VWAP (today's average traded price)")
        h1, _ = fetch(market, sym, "1h", 300 if market == "crypto" else "1mo")
        sh, sl = swings(h1[-150:])
    else:
        sh, sl = swings(daily[-250:])
    for c in cluster(sh, 0.3 * atr):
        add(c["price"], "swing_high", f"Swing high (price turned down here {c['touches']}x)", c["touches"])
    for c in cluster(sl, 0.3 * atr):
        add(c["price"], "swing_low", f"Swing low (price turned up here {c['touches']}x)", c["touches"])
    step = round_step(price)
    base = math.floor(price / step) * step
    for k in (-1, 0, 1, 2):
        add(base + k * step, "round", f"Round number {base + k * step:g}")
    # keep levels within a sensible band and annotate
    band = (12 if style == "intraday" else 25) * atr
    out = []
    for l in lv:
        d = l["price"] - price
        if abs(d) <= band:
            l.update({"side": "above" if d > 0 else "below", "dist_pct": round(d / price * 100, 3), "dist_atr": round(d / atr, 2)})
            out.append(l)
    out.sort(key=lambda x: x["price"])
    return {"computed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "symbol": display, "market": market,
            "style": style, "price": price, "atr": atr, "atr_timeframe": "1d" if style == "swing" else "1h", "levels": out,
            "nearest_above": next((l for l in out if l["price"] > price), None),
            "nearest_below": next((l for l in reversed(out) if l["price"] < price), None)}


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
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
        audit(os.path.dirname(os.path.abspath(a.out)), "levels", f"{len(res['levels'])} levels around {res['price']}")
        print(f"wrote {a.out}: {len(res['levels'])} levels; nearest below {res['nearest_below'] and res['nearest_below']['label']} "
              f"{res['nearest_below'] and res['nearest_below']['price']}, above {res['nearest_above'] and res['nearest_above']['label']} {res['nearest_above'] and res['nearest_above']['price']}")
    else:
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
