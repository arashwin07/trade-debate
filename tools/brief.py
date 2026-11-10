#!/usr/bin/env python3
"""Morning brief (M): one page before the bell.

  python tools/brief.py nse      # before NSE opens  -> docs/brief.json + docs/brief.html
  python tools/brief.py us       # before US opens
  python tools/brief.py all      # every market

Contents: data-source health, the market's mood (indexes, fear gauges, dollar), today's major scheduled
events, overnight moves in crypto and the main forex pairs, your watchlist (price, change, nearest floor
and ceiling, volatility), retake ideas still being watched, the Judge's track record and the practice
account. Plain language throughout.
"""
import json, os, sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import market_data as md, context, events, levels, regime, health, outcomes, paper, calibration  # noqa: E402


def safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def todays_events(markets):
    curr = set()
    for m in markets:
        curr |= {"crypto": {"USD"}, "us": {"USD"}, "nse": {"USD", "INR"}, "forex": {"USD", "EUR", "GBP", "JPY", "INR"}}[m]
    now = datetime.now(timezone.utc)
    evs, notes = events.macro_events(curr, now - timedelta(hours=2), now + timedelta(hours=24), now)
    for e in evs:
        e["tier"] = 1 if events.TIER1.search(e["title"] or "") else 2 if e["impact"] == "High" else 3
    return [e for e in evs if e["tier"] <= 2], notes


def watch_rows():
    wl = json.load(open(os.path.join(ROOT, "config", "watchlist.json"), encoding="utf-8")).get("items", [])
    rows = []
    for it in [i for i in wl if i.get("active", True)][:12]:
        lv = safe(levels.compute, it["symbol"], it["market"], it.get("style", "intraday"))
        rg = safe(regime.compute, it["symbol"], it["market"], it.get("style", "intraday"))
        if lv.get("error"):
            rows.append({"symbol": it["symbol"], "market": it["market"], "error": lv["error"]})
            continue
        nb, na = lv.get("nearest_below") or {}, lv.get("nearest_above") or {}
        rows.append({"symbol": lv["symbol"], "market": it["market"], "direction": it.get("direction"), "note": it.get("note"),
                     "price": lv["price"], "floor": nb.get("price"), "floor_label": nb.get("label"), "ceiling": na.get("price"),
                     "ceiling_label": na.get("label"), "volatility": rg.get("level"), "volatility_plain": rg.get("plain")})
    return rows


def overnight():
    out = []
    for sym, mk in (("BTC", "crypto"), ("ETH", "crypto"), ("EURUSD", "forex"), ("USDINR", "forex"), ("USDJPY", "forex")):
        try:
            s = md.build(sym, mk, "intraday", with_news=False)
            out.append({"symbol": s["symbol"], "price": s["price"], "change_pct": s.get("change_24h_pct", s.get("change_today_pct"))})
        except Exception as e:
            out.append({"symbol": sym, "error": type(e).__name__})
    return out


def retakes():
    base = os.path.join(ROOT, "debates")
    out = []
    for d in sorted(os.listdir(base)):
        r = outcomes.load(os.path.join(base, d, "retake.json"))
        if r and r.get("status") == "watching":
            v = outcomes.load(os.path.join(base, d, "verdict.json")) or {}
            out.append({"debate": d, "condition": v.get("retake_plain"), "last_price": r.get("last_price")})
    return out


def build(which):
    markets = ["nse", "us", "crypto", "forex"] if which == "all" else [which, "crypto", "forex"]
    mood = []
    for m in dict.fromkeys(["nse" if "nse" in markets else None, "us" if "us" in markets else None, "crypto"]):
        if m:
            c = safe(context.compute, {"nse": "RELIANCE", "us": "SPY", "crypto": "BTC"}[m], m, "LONG")
            mood.append({"market": m, "indexes": c.get("indexes"), "crypto_market": c.get("crypto_market"), "error": c.get("error")})
    evs, ev_notes = safe(todays_events, markets) if True else ([], [])
    h = safe(health.run)
    outcomes_summary = safe(outcomes.summary)
    cal = safe(calibration.run)
    pap = safe(paper.run)
    now = datetime.now(timezone.utc)
    title = {"nse": "Before NSE opens", "us": "Before Wall Street opens", "all": "Market brief"}.get(which, "Market brief")
    return {"computed_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "title": title, "which": which,
            "health": {"status": h.get("status"), "critical_down": h.get("critical_down"), "markets_down": h.get("markets_down")},
            "mood": mood, "events": evs, "event_notes": ev_notes, "overnight": overnight(), "watchlist": watch_rows(),
            "retakes": retakes(), "track": outcomes_summary, "calibration": {"plain": cal.get("plain"), "advice": cal.get("advice")},
            "paper": {"plain": pap.get("plain")}}


def render(data):
    with open(os.path.join(HERE, "ui", "brief.html"), encoding="utf-8") as f:
        html = f.read()
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    frag = html.replace("__DATA__", blob)
    head, body = frag.split("</style>", 1)
    page = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f"{head}</style></head><body>{body}</body></html>")
    with open(os.path.join(ROOT, "docs", "brief.html"), "w", encoding="utf-8") as f:
        f.write(page)
    with open(os.path.join(ROOT, "docs", "brief_artifact.html"), "w", encoding="utf-8") as f:
        f.write(frag)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    data = build(which)
    with open(os.path.join(ROOT, "docs", "brief.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    render(data)
    print(f"wrote docs/brief.html ({data['title']}): health {data['health']['status']}, {len(data['events'])} events, "
          f"{len(data['watchlist'])} watchlist rows, {len(data['retakes'])} retakes watching")


if __name__ == "__main__":
    main()
