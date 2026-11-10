#!/usr/bin/env python3
"""Trade journal: what really happened after each debate?

For every finished debate it replays the real price bars after the decision time:
  1. Did the price reach the entry? (a limit order at the entry price)
  2. After the fill, which came first: the stop or the first target? (a bar touching both counts as the stop)
  3. If neither by the end of the trade window, the result is marked to the last price.
It does this for SKIP calls too, so the Judge's track record shows the trades it avoided.

  python tools/outcomes.py            # update every debate's outcome.json (unfinished ones stay "pending")
  python tools/outcomes.py --summary  # print the track record
"""
import argparse, json, os, sys, urllib.parse
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import market_data  # noqa: E402
from desk import plan_from, load, save  # noqa: E402

INTRADAY_HOURS = 8
SWING_DAYS = 10


def ts(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


def bars_after(market, data_symbol, start, style):
    if market == "crypto":
        interval = "1d" if style == "swing" else "5m"
        rows = market_data.binance(f"/api/v3/klines?symbol={data_symbol}&interval={interval}&startTime={int(start * 1000)}&limit=1000")
        return [dict(t=r[0] // 1000, o=float(r[1]), h=float(r[2]), l=float(r[3]), c=float(r[4])) for r in rows]
    interval, rng = ("1d", "3mo") if style == "swing" else ("5m", "1mo")
    d = market_data.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(data_symbol)}?interval={interval}&range={rng}&includePrePost=false")
    res = d["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(res.get("timestamp") or []):
        if q["close"][i] is None or t < start - (86400 if style == "swing" else 0):
            continue
        out.append(dict(t=t, o=q["open"][i] or q["close"][i], h=q["high"][i], l=q["low"][i], c=q["close"][i]))
    return out


def evaluate(plan, bars, start, end, now):
    """Pure function: plan + bars (time-ordered) -> outcome dict."""
    long = plan["direction"] == "LONG"
    e, s, t1 = plan["entry"], plan["stop"], plan["targets"][0]
    risk = abs(e - s)
    window = [b for b in bars if start <= b["t"] < end]
    filled_at = None
    for i, b in enumerate(window):
        if b["l"] <= e <= b["h"]:
            filled_at = i
            break
    over = now >= end
    if filled_at is None:
        return {"status": "not_filled" if over else "pending", "r": None,
                "plain": "The price never reached the entry, so the trade would not have started." if over else "Waiting for the price to reach the entry."}
    hits = {}
    for b in window[filled_at:]:
        stop_hit = (b["l"] <= s) if long else (b["h"] >= s)
        if stop_hit:
            return {"status": "stop", "r": -1.0, "filled_utc": iso(window[filled_at]["t"]), "closed_utc": iso(b["t"]),
                    "targets_hit_before_stop": len(hits), "plain": "Hit the safety exit (stop-loss) first: a loss of 1x the risk."}
        for k, t in enumerate(plan["targets"]):
            if k not in hits and ((b["h"] >= t) if long else (b["l"] <= t)):
                hits[k] = b["t"]
        if 0 in hits:
            r1 = abs(t1 - e) / risk
            return {"status": "target", "r": round(r1, 3), "filled_utc": iso(window[filled_at]["t"]), "closed_utc": iso(b["t"]),
                    "plain": f"Reached the first target before the stop: a gain of {r1:.2f}x the risk."}
    if not over:
        return {"status": "pending", "r": None, "filled_utc": iso(window[filled_at]["t"]), "plain": "Entry reached; the trade is still open."}
    last = window[-1]["c"]
    r = ((last - e) if long else (e - last)) / risk
    return {"status": "expired", "r": round(r, 3), "filled_utc": iso(window[filled_at]["t"]),
            "plain": f"Neither the target nor the stop was hit in time; closing at the end would give {r:+.2f}x the risk."}


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def update(folder, now=None):
    now = now or datetime.now(timezone.utc).timestamp()
    meta = load(os.path.join(folder, "meta.json"), {})
    verdict = load(os.path.join(folder, "verdict.json"))
    if not verdict:
        return None
    final = load(os.path.join(folder, "desk_final.json"), {})
    prev = load(os.path.join(folder, "outcome.json"), {})
    if prev.get("status") in ("target", "stop", "expired", "not_filled", "no_plan") and ("r_gross" in prev or prev.get("r") is None):
        return prev  # final results are kept; older results recorded before costs were added are re-evaluated once
    snap = load(os.path.join(folder, "snapshot.json"), {})
    market, data_symbol, display = market_data.detect(snap.get("data_symbol") or meta.get("symbol"), snap.get("market") or meta.get("market") or "auto")
    style = snap.get("style") or meta.get("style") or "intraday"
    plan = final.get("plan") or plan_from(verdict, meta.get("direction", "LONG"))
    if not plan:
        for r in (3, 2, 1):
            plan = plan_from(load(os.path.join(folder, f"r{r}_bull.json")), meta.get("direction", "LONG"))
            if plan:
                break
    call = final.get("final_call") or ("TAKE" if str(verdict.get("decision", "")).upper() in ("TAKE", "BUY") else "SKIP")
    out = {"checked_utc": iso(now), "call": call, "judge_decision": verdict.get("decision"), "plan": plan}
    if not plan:
        out.update({"status": "no_plan", "r": None, "plain": "No trade plan with numbers was recorded for this debate."})
        save(os.path.join(folder, "outcome.json"), out)
        return out
    start = ts(final.get("computed_utc") or verdict.get("_written") or meta.get("created_utc"))
    if "_written" not in verdict and not final:
        start = os.path.getmtime(os.path.join(folder, "verdict.json"))
    end = start + (SWING_DAYS * 86400 * 1.5 if style == "swing" else INTRADAY_HOURS * 3600)
    try:
        bars = bars_after(market, data_symbol, start, style)
    except Exception as e:
        out.update({"status": "pending", "r": None, "plain": f"Could not load prices ({type(e).__name__}); will retry."})
        save(os.path.join(folder, "outcome.json"), out)
        return out
    if style == "swing":
        bars = [b for b in bars if b["t"] >= start - 86400][: SWING_DAYS + 1]
        end = (bars[-1]["t"] + 86400) if len(bars) > SWING_DAYS else end
    res = evaluate(plan, bars, start, end, now)
    if res.get("r") is not None:  # results are recorded AFTER costs (fees, taxes, spread, slippage) for one unit
        try:
            import desk
            long = plan["direction"] == "LONG"
            exit_px = plan["stop"] if res["status"] == "stop" else plan["targets"][0] if res["status"] == "target" else \
                plan["entry"] + res["r"] * abs(plan["entry"] - plan["stop"]) * (1 if long else -1)
            cost, _ = desk.round_trip_cost(market, style, long, plan["entry"], exit_px, 1.0, desk.config()["costs"], desk.pip_size(market, data_symbol))
            res["r_gross"] = res["r"]
            res["cost_r"] = round(cost / abs(plan["entry"] - plan["stop"]), 3)
            res["r"] = round(desk.after_tax(res["r"] - res["cost_r"], market, desk.config()["costs"]), 3)  # profits after tax where it applies
        except Exception as e:
            res["cost_note"] = f"costs not applied ({type(e).__name__})"
    out.update(res)
    out["window_end_utc"] = iso(end)
    save(os.path.join(folder, "outcome.json"), out)
    return out


def summary():
    base = os.path.join(ROOT, "debates")
    rows = []
    for d in sorted(os.listdir(base)):
        o = load(os.path.join(base, d, "outcome.json"))
        if o:
            rows.append((d, o))
    def stats(call):
        rs = [o for _, o in rows if o.get("call") == call and o.get("status") in ("target", "stop", "expired")]
        wins = sum(1 for o in rs if (o.get("r") or 0) > 0)
        return {"resolved": len(rs), "wins": wins, "losses": len(rs) - wins,
                "avg_r": round(sum(o["r"] for o in rs) / len(rs), 3) if rs else None,
                "not_filled": sum(1 for _, o in rows if o.get("call") == call and o.get("status") == "not_filled"),
                "pending": sum(1 for _, o in rows if o.get("call") == call and o.get("status") == "pending")}
    return {"take": stats("TAKE"), "skip": stats("SKIP"), "debates": len(rows)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if not a.summary:
        base = os.path.join(ROOT, "debates")
        for d in sorted(os.listdir(base)):
            f = os.path.join(base, d)
            if os.path.isdir(f) and os.path.exists(os.path.join(f, "verdict.json")):
                o = update(f)
                print(f"{d}: {o.get('call')} -> {o.get('status')} {'' if o.get('r') is None else f'({o[chr(114)]:+.2f}R)'}")
    print(json.dumps(summary(), indent=2))


if __name__ == "__main__":
    main()
