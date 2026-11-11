#!/usr/bin/env python3
"""Watchlist (W) + retake watcher (R).

  python tools/watch.py watchlist          # prints the active watchlist entries whose market is open now (JSON)
  python tools/watch.py retake             # checks every SKIP's retake condition against live prices;
                                           # met ones go to debates/_retake_queue.json for a fresh debate

Retake conditions come from the Judge's verdict as numbers (`retake_numbers`):
  {"price_above": 172.0, "price_below": null, "hold_minutes": 60, "expires_hours": 24}
"price_above" is met when every 5-minute close of the last `hold_minutes` is above it (price_below: below).
Each condition fires once; it expires after `expires_hours` (default 24 intraday, 120 swing).
"""
import json, os, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import market_data as md  # noqa: E402
from audit import audit  # noqa: E402


def load(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save(p, o):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(o, f, indent=2, ensure_ascii=False)


def market_open(market):
    now = datetime.now(timezone.utc)
    if market == "crypto":
        return True
    if market == "forex":
        wd = now.weekday()
        return not (wd == 5 or (wd == 4 and now.hour >= 22) or (wd == 6 and now.hour < 22))
    try:
        _, meta = md.candles_yahoo("AAPL" if market == "us" else "^NSEI", "1d", "1d")
        p = (meta.get("currentTradingPeriod") or {}).get("regular", {})
        return p.get("start", 0) <= now.timestamp() <= p.get("end", 0)
    except Exception:
        return False


def norm(symbol, market):
    """One key per instrument, whatever way it was written (BTC, BTCUSDT, BTC/USDT; RELIANCE, RELIANCE.NS)."""
    try:
        _, data_sym, _ = md.detect(str(symbol), market or "auto")
    except Exception:
        data_sym = str(symbol)
    return "".join(ch for ch in data_sym.upper() if ch.isalnum())


def recently_debated(symbol, market, direction, hours=20, debates_dir=None):
    """The id of a debate of this same trade in the last `hours`, or None."""
    debates_dir = debates_dir or os.path.join(ROOT, "debates")
    key, cut = norm(symbol, market), datetime.now(timezone.utc).timestamp() - hours * 3600
    if not os.path.isdir(debates_dir):
        return None
    for name in sorted(os.listdir(debates_dir), reverse=True):
        meta = load(os.path.join(debates_dir, name, "meta.json"))
        if not meta:
            continue
        try:
            made = datetime.fromisoformat(meta["created_utc"].replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
        if made < cut:
            continue
        if norm(meta.get("symbol", ""), meta.get("market")) == key and str(meta.get("direction") or "LONG").upper() == direction.upper():
            return meta.get("id") or name
    return None


def watchlist():
    """Active entries whose time is right, minus any already debated in the last 20 hours (once a day is enough)."""
    wl = load(os.path.join(ROOT, "config", "watchlist.json"), {"items": []})
    out = []
    for it in wl.get("items", []):
        if not it.get("active", True):
            continue
        if not (market_open(it["market"]) or it.get("style") == "swing"):
            continue
        if recently_debated(it["symbol"], it["market"], it.get("direction", "LONG")):
            continue
        out.append(it)
    return out


def recent_closes(market, data_sym, minutes):
    n = max(1, int(minutes // 5))
    if market == "crypto":
        cs = md.candles_binance(data_sym, "5m", n + 2)
    else:
        cs, _ = md.candles_yahoo(data_sym, "5m", "1d")
    cs = cs[:-1]  # drop the still-forming bar
    return [c["c"] for c in cs[-n:]], (cs[-1]["c"] if cs else None)


def retake():
    base = os.path.join(ROOT, "debates")
    qpath = os.path.join(base, "_retake_queue.json")
    queue = load(qpath, [])
    now = datetime.now(timezone.utc)
    report = []
    for d in sorted(os.listdir(base)):
        f = os.path.join(base, d)
        v = load(os.path.join(f, "verdict.json"))
        fin = load(os.path.join(f, "desk_final.json"), {})
        if not v or (fin.get("final_call") or v.get("decision")) != "SKIP":
            continue
        rn = v.get("retake_numbers")
        st = load(os.path.join(f, "retake.json"), {})
        if not rn or st.get("status") in ("fired", "expired"):
            continue
        meta = load(os.path.join(f, "meta.json"), {})
        snap = load(os.path.join(f, "snapshot.json"), {})
        market, data_sym, display = md.detect(snap.get("data_symbol") or meta["symbol"], snap.get("market") or meta["market"])
        made = datetime.fromisoformat((fin.get("computed_utc") or meta["created_utc"]).replace("Z", "+00:00"))
        hours = rn.get("expires_hours") or (120 if meta.get("style") == "swing" else 24)
        if (now - made).total_seconds() > hours * 3600:
            save(os.path.join(f, "retake.json"), {"status": "expired", "checked_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ")})
            report.append(f"{d}: retake window expired")
            continue
        if not market_open(market):
            report.append(f"{d}: market closed, not checked")
            continue
        try:
            closes, last = recent_closes(market, data_sym, rn.get("hold_minutes") or 30)
        except Exception as e:
            report.append(f"{d}: price check failed ({type(e).__name__})")
            continue
        above, below = rn.get("price_above"), rn.get("price_below")
        met = bool(closes) and ((above is not None and all(c > above for c in closes)) or (below is not None and all(c < below for c in closes)))
        status = {"status": "fired" if met else "watching", "checked_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "last_price": last,
                  "condition": rn}
        save(os.path.join(f, "retake.json"), status)
        if met:
            queue.append({"from_debate": d, "symbol": display, "market": market, "direction": meta.get("direction", "LONG"),
                          "style": meta.get("style", "intraday"), "reason": f"retake condition met: {v.get('retake_plain', '')[:200]}",
                          "queued_utc": status["checked_utc"]})
            audit(f, "retake", f"FIRED at {last}: {rn}")
        report.append(f"{d}: {'CONDITION MET -> queued for a new debate' if met else 'watching'} (last {last}, condition {rn})")
    save(qpath, queue)
    return report, queue


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "retake"
    if cmd == "watchlist":
        print(json.dumps(watchlist(), indent=2, ensure_ascii=False))
    else:
        report, queue = retake()
        for r in report:
            print(r)
        print(f"queue: {len(queue)} waiting")


if __name__ == "__main__":
    main()
