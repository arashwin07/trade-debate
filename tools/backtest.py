#!/usr/bin/env python3
"""Backtest (B): would the desk's simple rules have made money on this asset recently?

  python tools/backtest.py ETH --market crypto --direction LONG
  python tools/backtest.py RELIANCE --market nse --direction LONG --out docs/backtest_RELIANCE.json

Uses the same 60 days of 5-minute bars as the Time Machine (code only, no AI, so it is cheap and repeatable).
At several start times every past day (every 2 hours for 24h markets, 3 times per session for stocks):
  plan  : enter at that bar's close, stop 1x ATR (1-hour ATR built from the 5m bars), target 1.5x ATR
  window: 8 hours (crypto/forex) or the rest of the session (stocks); a bar touching both counts as the stop
  costs : per-unit round-trip costs from config/desk.json are taken off every result
Then it compares entry filters, so you can see which rule has had an edge here:
  ALL          take every start
  TREND        only when the 1h EMA9 is above EMA21 (below, for a short)
  PULLBACK     only when the 1h RSI is under 40 (over 60, for a short)
  TREND+PULL   both
Results in R (multiples of the risk) after costs. Past results do not guarantee future ones; 60 days is a small sample.
"""
import argparse, json, os, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import market_data as md, timemachine as tm, desk  # noqa: E402

STOP_ATR, TARGET_ATR = 1.0, 1.5


def hourly(bars):
    out, cur = [], None
    for b in bars:
        h = b["t"] // 3600
        if cur and cur["k"] == h:
            cur["h"], cur["l"], cur["c"] = max(cur["h"], b["h"]), min(cur["l"], b["l"]), b["c"]
        else:
            cur = {"k": h, "t": b["t"], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"]}
            out.append(cur)
    return out


def indicators(hb):
    """Per hourly bar: ATR14, EMA9, EMA21, RSI14 (values known at that bar's close)."""
    res, atr, e9, e21, ag, al = [], None, None, None, None, None
    k9, k21 = 2 / 10, 2 / 22
    for i, b in enumerate(hb):
        if i == 0:
            e9 = e21 = b["c"]
            res.append(None)
            continue
        p = hb[i - 1]
        tr = max(b["h"] - b["l"], abs(b["h"] - p["c"]), abs(b["l"] - p["c"]))
        atr = tr if atr is None else (atr * 13 + tr) / 14
        e9, e21 = b["c"] * k9 + e9 * (1 - k9), b["c"] * k21 + e21 * (1 - k21)
        g, l = max(b["c"] - p["c"], 0), max(p["c"] - b["c"], 0)
        ag = g if ag is None else (ag * 13 + g) / 14
        al = l if al is None else (al * 13 + l) / 14
        rsi = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
        res.append({"atr": atr, "e9": e9, "e21": e21, "rsi": rsi} if i >= 21 else None)
    return res


def run(symbol, market="auto", direction="LONG", hours=8.0):
    cfg = desk.config()
    market, data_sym, display = md.detect(symbol, market)
    bars, offset = tm.load_bars(market, data_sym, "intraday")
    long = direction.upper() == "LONG"
    hb = hourly(bars)
    ind = indicators(hb)
    hour_idx = {h["k"]: i for i, h in enumerate(hb)}
    round_clock = market in ("crypto", "forex")
    steps_max = int(hours * 12)
    trades = []
    for i, b in enumerate(bars[:-1]):
        local_min = ((b["t"] + offset) % 86400) // 60
        if round_clock:
            if local_min % 120 != 0:
                continue
        else:
            # three starts per session: 1h, 2.5h and 4h after the session's first bar
            day = (b["t"] + offset) // 86400
            first = next((x for x in bars if (x["t"] + offset) // 86400 == day), None)
            if not first or (b["t"] - first["t"]) not in (3600, 9000, 14400):
                continue
        hi = hour_idx.get(b["t"] // 3600 - 1)  # last COMPLETED hour: no peeking
        if hi is None or ind[hi] is None:
            continue
        x = ind[hi]
        e, atr = b["c"], x["atr"]
        stop = e - STOP_ATR * atr if long else e + STOP_ATR * atr
        tgt = e + TARGET_ATR * atr if long else e - TARGET_ATR * atr
        c_stop, _ = desk.round_trip_cost(market, "intraday", long, e, stop, 1.0, cfg["costs"], desk.pip_size(market, data_sym))
        risk = abs(e - stop)
        out, last = None, e
        for j in range(i + 1, min(len(bars), i + 1 + steps_max)):
            nb = bars[j]
            if nb["t"] - bars[j - 1]["t"] != 300:
                break  # session end or gap
            if (nb["l"] <= stop) if long else (nb["h"] >= stop):
                out = -1.0
                break
            if (nb["h"] >= tgt) if long else (nb["l"] <= tgt):
                out = TARGET_ATR / STOP_ATR
                break
            last = nb["c"]
        if out is None:
            out = ((last - e) if long else (e - last)) / risk
        r_net = out - c_stop / risk  # costs expressed in R
        trend_ok = (x["e9"] > x["e21"]) if long else (x["e9"] < x["e21"])
        pull_ok = (x["rsi"] < 40) if long else (x["rsi"] > 60)
        trades.append({"t": b["t"], "r": round(r_net, 3), "trend": trend_ok, "pull": pull_ok})

    def stats(rows):
        if not rows:
            return {"n": 0}
        wins = sum(1 for r in rows if r["r"] > 0)
        return {"n": len(rows), "win_rate_pct": round(100 * wins / len(rows), 1), "avg_r": round(sum(r["r"] for r in rows) / len(rows), 3),
                "total_r": round(sum(r["r"] for r in rows), 2)}

    res = {
        "ALL": stats(trades), "TREND": stats([t for t in trades if t["trend"]]),
        "PULLBACK": stats([t for t in trades if t["pull"]]), "TREND+PULL": stats([t for t in trades if t["trend"] and t["pull"]]),
    }
    best = max((k for k in res if res[k].get("n", 0) >= 15), key=lambda k: res[k]["avg_r"], default=None)
    plain = f"Over the last {len({t['t'] // 86400 for t in trades})} days, a {direction.lower()} with a 1x ATR stop and 1.5x ATR target on {display} averaged "
    plain += f"{res['ALL'].get('avg_r', 0):+.2f}R per trade after costs across {res['ALL'].get('n', 0)} starts."
    if best and res[best]["avg_r"] > 0:
        plain += f" The best filter was {best}: {res[best]['avg_r']:+.2f}R over {res[best]['n']} trades ({res[best]['win_rate_pct']}% winners)."
    else:
        plain += " No filter made money on average in this period."
    return {"computed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "symbol": display, "market": market, "direction": direction,
            "rules": {"stop_atr": STOP_ATR, "target_atr": TARGET_ATR, "window_hours": hours, "costs": "included"},
            "results": res, "best_filter": best, "plain": plain,
            "caveat": "60 days of history is a small sample; past results do not guarantee future ones."}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--market", default="auto")
    ap.add_argument("--direction", default="LONG")
    ap.add_argument("--out")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    res = run(a.symbol, a.market, a.direction.upper())
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
        print(f"wrote {a.out}: {res['plain']}")
    else:
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
