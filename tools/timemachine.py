#!/usr/bin/env python3
"""Time Machine for every market: the honest odds of a trade plan before any money is at risk.

Idea adapted from the MIT-licensed day-trader-skill (trader-timemachine), rebuilt for crypto, US stocks,
NSE and forex, intraday and swing:

1. Replays (Monte Carlo): start at the entry price and rebuild the rest of the trade window bar by bar,
   10,000 times. Each bar is drawn from the asset's OWN past bars at the same time of day (+-2 bars),
   scaled to the current price. Stop is checked before target inside a bar (a bar that touches both
   counts as the stop: the cautious choice).
2. Real history: the same stop and target DISTANCES (in %) are walked forward through every real past
   day from the same time of day. That is what actually happened, not a simulation.
3. Verdict: does the target come first often enough to pay for the risk? At a target of R times the risk,
   break-even needs the target first in 1 / (1 + R) of the replays that hit a side.

Same plan + same data + same seed = same numbers. Not a prediction: earnings, news and halts can do
things the last 60 days never did.

Usage:
  python tools/timemachine.py --symbol ETH --market crypto --direction LONG --entry 2068 --stop 2047 --target 2096 --target 2113
  python tools/timemachine.py --symbol RELIANCE --market nse --style swing --direction LONG --entry 1324 --stop 1290 --target 1390 --out x.json
"""
import argparse, json, math, os, random, statistics, sys, time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from market_data import detect, binance, get  # noqa: E402

REPLAYS, SEED, WINDOW = 10000, 19, 2
COIN_FLIP, STRONG = 0.05, 0.15
MIN_DAYS = 20


# ---------------------------------------------------------------- data
def bars_binance(sym, interval, days):
    step = {"5m": 300, "1d": 86400}[interval]
    need = int(days * 86400 / step)
    out, end = [], None
    while len(out) < need:
        q = f"/api/v3/klines?symbol={sym}&interval={interval}&limit=1000" + (f"&endTime={end}" if end else "")
        rows = binance(q)
        if not rows:
            break
        chunk = [dict(t=r[0] // 1000, o=float(r[1]), h=float(r[2]), l=float(r[3]), c=float(r[4])) for r in rows]
        out = chunk + out
        end = rows[0][0] - 1
        if len(rows) < 1000:
            break
    return out[-need:], 0  # crypto: UTC clock


def bars_yahoo(sym, interval, rng):
    import urllib.parse
    d = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?interval={interval}&range={rng}&includePrePost=false")
    res = d["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(res.get("timestamp") or []):
        c = q["close"][i]
        if c is None or q["high"][i] is None or q["low"][i] is None:
            continue
        out.append(dict(t=t, o=q["open"][i] or c, h=q["high"][i], l=q["low"][i], c=c))
    return out, int(res["meta"].get("gmtoffset") or 0)


def load_bars(market, data_sym, style):
    if style == "swing":
        return bars_binance(data_sym, "1d", 730) if market == "crypto" else bars_yahoo(data_sym, "1d", "2y")
    if market == "crypto":
        return bars_binance(data_sym, "5m", 60)
    gm = bars_yahoo(data_sym, "5m", "60d")
    return (gm[0], 0) if market == "forex" else gm  # forex trades round the clock: use UTC like crypto


# ---------------------------------------------------------------- pool
def day_and_slot(t, offset, bar):
    local = t + offset
    return local // 86400, (local % 86400) // bar


def build(bars, offset, style):
    """Return pool[slot] -> [(o,h,l,c) ratios to the previous close], plus per-day sequences for history."""
    bar = 86400 if style == "swing" else 300
    pool, days = {}, {}
    prev = None
    for b in bars:
        d, s = day_and_slot(b["t"], offset, bar) if style != "swing" else (0, 0)
        days.setdefault(d, []).append((s, b))
        # only consecutive bars: no overnight gap inside an intraday pool (a 24h market has no gaps)
        if prev is not None and (style == "swing" or b["t"] - prev["t"] == bar):
            pc = prev["c"]
            if pc > 0:
                pool.setdefault(s, []).append((b["o"] / pc, b["h"] / pc, b["l"] / pc, b["c"] / pc))
        prev = b
    return pool, days


def slot_order(pool, style, market):
    slots = sorted(pool)
    round_clock = market in ("crypto", "forex") or style == "swing"
    return slots, round_clock


# ---------------------------------------------------------------- simulation
def simulate(pool, slots, round_clock, start_slot, steps, entry, stop, targets, long, replays=REPLAYS, seed=SEED, window=WINDOW):
    risk = (entry - stop) if long else (stop - entry)
    if risk <= 0:
        raise ValueError("stop is on the wrong side of the entry")
    for t in targets:
        if (t <= entry) if long else (t >= entry):
            raise ValueError("a target is on the wrong side of the entry")
    r_target = ((targets[0] - entry) if long else (entry - targets[0])) / risk
    idx = {s: i for i, s in enumerate(slots)}
    # path of slots for this window
    if round_clock:
        i0 = idx.get(start_slot, min(range(len(slots)), key=lambda i: abs(slots[i] - start_slot)))
        path = [slots[(i0 + j) % len(slots)] for j in range(steps)]
    else:
        later = [s for s in slots if s >= start_slot] or slots
        path = later[:steps]
    if not path:
        raise ValueError("no bars left in the session to simulate")
    neighbours = []
    for s in path:
        i = idx[s]
        if len(slots) == 1:
            cand = pool[s]
        else:
            lo, hi = i - window, i + window
            js = [(j % len(slots)) for j in range(lo, hi + 1)] if round_clock else [j for j in range(max(0, lo), min(len(slots) - 1, hi) + 1)]
            cand = [x for j in js for x in pool[slots[j]]]
        neighbours.append(cand)
    rng = random.Random(seed)
    n_t = len(targets)
    tgt_first = [0] * n_t
    outcome_count = {"target": 0, "stop": 0, "neither": 0}
    closes, Rs, green = [], [], 0
    for _ in range(replays):
        p = entry
        stop_at = None
        hit = [None] * n_t
        for j, cand in enumerate(neighbours):
            o, h, l, c = cand[rng.randrange(len(cand))]
            hi_, lo_ = p * h, p * l
            if stop_at is None:
                if (lo_ <= stop) if long else (hi_ >= stop):
                    stop_at = j
                for k in range(n_t):
                    if hit[k] is None and stop_at is None and ((hi_ >= targets[k]) if long else (lo_ <= targets[k])):
                        hit[k] = j
            p = p * c
        for k in range(n_t):
            if hit[k] is not None:
                tgt_first[k] += 1
        if hit[0] is not None:
            outcome_count["target"] += 1
            R = r_target
        elif stop_at is not None:
            outcome_count["stop"] += 1
            R = -1.0
        else:
            outcome_count["neither"] += 1
            R = ((p - entry) if long else (entry - p)) / risk
        Rs.append(R)
        closes.append(p)
        if R > 0:
            green += 1
    srt = sorted(closes)
    pc = lambda q: srt[min(len(srt) - 1, int(q * len(srt)))]
    return {
        "replays": replays, "seed": seed, "window_bars": window, "steps": len(path),
        "p_target": round(outcome_count["target"] / replays, 4), "p_stop": round(outcome_count["stop"] / replays, 4),
        "p_neither": round(outcome_count["neither"] / replays, 4), "p_green": round(green / replays, 4),
        "p_each_target_before_stop": [round(x / replays, 4) for x in tgt_first],
        "median_end": round(pc(0.5), 6), "p5_end": round(pc(0.05), 6), "p95_end": round(pc(0.95), 6),
        "avg_R": round(statistics.mean(Rs), 3), "r_at_target": round(r_target, 3),
    }


# ---------------------------------------------------------------- real history
def history(days, round_clock, start_slot, steps, entry, stop, target, long, today_key, style, bars):
    stop_pct = abs(entry - stop) / entry
    tgt_pct = abs(target - entry) / entry
    res = {"target": 0, "stop": 0, "neither": 0}
    starts = []
    if style == "swing":
        seq = [b for b in bars]
        for i in range(len(seq) - steps - 1):
            starts.append((seq[i]["c"], seq[i + 1:i + 1 + steps]))
    else:
        flat = [b for d in sorted(days) for _, b in days[d]]
        pos = {id(b): i for i, b in enumerate(flat)}
        for d in sorted(days):
            if d == today_key:
                continue
            row = [b for s, b in days[d] if s == start_slot]
            if not row:
                continue
            i = pos[id(row[0])]
            seg = []
            for b in flat[i + 1:i + 1 + steps]:
                if b["t"] - (seg[-1]["t"] if seg else row[0]["t"]) != 300:
                    break  # stop at a gap (session end or missing data)
                seg.append(b)
            if seg:
                starts.append((row[0]["c"], seg))
    for e0, seg in starts:
        st = e0 * (1 - stop_pct) if long else e0 * (1 + stop_pct)
        tg = e0 * (1 + tgt_pct) if long else e0 * (1 - tgt_pct)
        out = "neither"
        for b in seg:
            if (b["l"] <= st) if long else (b["h"] >= st):
                out = "stop"
                break
            if (b["h"] >= tg) if long else (b["l"] <= tg):
                out = "target"
                break
        res[out] += 1
    n = sum(res.values())
    return {"samples": n, **res, "target_rate": round(res["target"] / n, 4) if n else None,
            "stop_rate": round(res["stop"] / n, 4) if n else None,
            "note": "overlapping windows" if style == "swing" else "one sample per past day, same time of day"}


# ---------------------------------------------------------------- verdict
def verdict(mc):
    pt, ps = mc["p_target"], mc["p_stop"]
    if pt + ps <= 0:
        return "NEUTRAL", "No replay reached the target or the stop inside the window; the price at the end decides everything."
    r = mc["r_at_target"] or 1.0
    share, even = pt / (pt + ps), 1.0 / (1.0 + r)
    d = share - even
    if abs(d) < COIN_FLIP:
        lean, head = "COIN_FLIP", "Close to break-even"
    elif abs(d) < STRONG:
        lean, head = ("LEANS_TARGET", "Leans toward the target") if d > 0 else ("LEANS_STOP", "Leans toward the stop")
    else:
        lean, head = ("STRONG_TARGET", "Strongly toward the target") if d > 0 else ("STRONG_STOP", "Strongly toward the stop")
    line = (f"{head}: at {r:.2f}R the target must come first in {100 * even:.0f}% of the replays that hit a side; "
            f"it did in {100 * share:.0f}% (target first {100 * pt:.1f}% vs stop first {100 * ps:.1f}%).")
    return lean, line


def plain_summary(mc, hist, lean, style):
    window = "the trading window" if style == "intraday" else "the holding period"
    s = (f"We replayed {window} {mc['replays']:,} times using this market's own recent price moves. "
         f"The first target was reached before the safety exit in {100 * mc['p_target']:.0f}% of replays, "
         f"the safety exit was hit first in {100 * mc['p_stop']:.0f}%, and in {100 * mc['p_neither']:.0f}% neither happened in time.")
    if hist["samples"]:
        s += (f" In real history ({hist['samples']} past starts), the same distances hit the target first {hist['target']} times "
              f"and the stop first {hist['stop']} times.")
    s += {"COIN_FLIP": " Overall: about a coin flip once the reward size is counted.",
          "LEANS_TARGET": " Overall: the odds lean slightly in favour of the trade.",
          "STRONG_TARGET": " Overall: the odds lean clearly in favour of the trade.",
          "LEANS_STOP": " Overall: the odds lean slightly against the trade.",
          "STRONG_STOP": " Overall: the odds lean clearly against the trade.",
          "NEUTRAL": " Overall: price rarely reaches either level in time."}[lean]
    return s


# ---------------------------------------------------------------- main
def prepare(symbol, market, style="intraday", hours=8.0, days=10, now=None):
    """Download and pool the history once; reuse it for many plans (the optimizer tries dozens)."""
    market, data_sym, display = detect(symbol, market)
    bars, offset = load_bars(market, data_sym, style)
    if len(bars) < 50:
        raise ValueError(f"not enough history ({len(bars)} bars)")
    now = now or time.time()
    pool, days_map = build(bars, offset, style)
    slots, round_clock = slot_order(pool, style, market)
    n_days = len(days_map) if style != "swing" else len(bars)
    if style != "swing" and n_days < MIN_DAYS:
        raise ValueError(f"only {n_days} days of 5-minute data; need {MIN_DAYS}")
    notes = []
    if style == "swing":
        steps, start_slot, today_key = int(days), 0, None
    else:
        today_key, cur = day_and_slot(int(now), offset, 300)
        start_slot = cur + 1
        if not round_clock and (start_slot > max(slots) or start_slot < min(slots)):
            start_slot = min(slots)
            notes.append("Market is closed now: replays start from the next session's open.")
        steps = int(hours * 12)
        if not round_clock:
            left = len([s for s in slots if s >= start_slot])
            if left < steps:
                notes.append(f"Only {left * 5} minutes of the session are left, so the window ends at the close.")
                steps = left
    return {"market": market, "display": display, "style": style, "bars": bars, "pool": pool, "days_map": days_map,
            "slots": slots, "round_clock": round_clock, "n_days": n_days, "steps": steps, "start_slot": start_slot,
            "today_key": today_key, "notes": notes}


def run_plan(ctx, direction, entry, stop, targets, replays=REPLAYS, seed=SEED, with_history=True):
    long = direction.upper() == "LONG"
    mc = simulate(ctx["pool"], ctx["slots"], ctx["round_clock"], ctx["start_slot"], ctx["steps"], entry, stop, targets, long, replays, seed)
    hist = (history(ctx["days_map"], ctx["round_clock"], ctx["start_slot"], ctx["steps"], entry, stop, targets[0], long,
                    ctx["today_key"], ctx["style"], ctx["bars"]) if with_history else {"samples": 0, "target": 0, "stop": 0, "neither": 0})
    lean, line = verdict(mc)
    return mc, hist, lean, line


def run(symbol, market, direction, entry, stop, targets, style="intraday", hours=8.0, days=10, replays=REPLAYS, seed=SEED, now=None, ctx=None):
    ctx = ctx or prepare(symbol, market, style, hours, days, now)
    mc, hist, lean, line = run_plan(ctx, direction, entry, stop, targets, replays, seed)
    long = direction.upper() == "LONG"
    steps = ctx["steps"]
    return {
        "computed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plan": {"symbol": ctx["display"], "market": ctx["market"], "style": style, "direction": "LONG" if long else "SHORT",
                 "entry": entry, "stop": stop, "targets": targets,
                 "window": f"{steps * 5} minutes" if style != "swing" else f"{steps} trading days"},
        "data": {"bars": len(ctx["bars"]), "days": ctx["n_days"], "source": "Binance" if ctx["market"] == "crypto" else "Yahoo Finance",
                 "interval": "1d" if style == "swing" else "5m"},
        "mc": mc, "history": hist, "lean": lean, "verdict": line,
        "plain": plain_summary(mc, hist, lean, style), "notes": ctx["notes"],
        "caveat": "A simulation from recent bars, not a prediction. News, earnings and gaps can do what the last 60 days never did.",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--market", default="auto", choices=["auto", "crypto", "us", "nse", "forex"])
    ap.add_argument("--style", default="intraday", choices=["intraday", "swing"])
    ap.add_argument("--direction", required=True, choices=["LONG", "SHORT", "long", "short"])
    ap.add_argument("--entry", type=float, required=True)
    ap.add_argument("--stop", type=float, required=True)
    ap.add_argument("--target", type=float, action="append", required=True)
    ap.add_argument("--hours", type=float, default=8.0, help="intraday window length")
    ap.add_argument("--days", type=int, default=10, help="swing holding period in trading days")
    ap.add_argument("--replays", type=int, default=REPLAYS)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out")
    a = ap.parse_args()
    try:
        res = run(a.symbol, a.market, a.direction, a.entry, a.stop, a.target, a.style, a.hours, a.days, a.replays, a.seed)
    except Exception as e:
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}), file=sys.stderr)
        sys.exit(1)
    text = json.dumps(res, indent=2)
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        open(a.out, "w", encoding="utf-8").write(text)
        print(f"wrote {a.out}: {res['verdict']}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)


if __name__ == "__main__":
    main()
