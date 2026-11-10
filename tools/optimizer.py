#!/usr/bin/env python3
"""Plan optimizer (O): before any debate, code searches for the best plan that passes YOUR rules.

  python tools/optimizer.py debates/<id>                 # uses meta.json + levels.json -> optimizer.json
  python tools/optimizer.py --symbol ETH --market crypto --direction LONG [--style swing]

Candidates are built only from real levels (levels.py) and ATR multiples:
  entry  : the live price, or a limit at the nearest helpful level within 0.6 ATR
  stop   : just beyond a real level on the losing side (+0.15 ATR buffer), or 1.0 / 1.5 / 2.0 ATR;
           always between the rule's minimum (min_stop_atr) and 3 ATR
  target : just before a real level on the winning side (-0.1 ATR), or 2R / 3R
Each candidate must pay at least min_reward_risk_after_costs to the first target AFTER costs, then gets
3,000 Time Machine replays (same pooled history for all, seed 19). Ranked by average result in R.
If nothing passes, it says so: that is a strong reason to skip the trade.
"""
import argparse, json, os, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import desk, levels as levels_mod, timemachine as tm, market_data as md  # noqa: E402
from audit import audit  # noqa: E402

REPLAYS = 1500          # screening replays per candidate (finalists get 10,000 + real history)
MAX_TARGET_ATR = 4.0    # a target further than this many ATR is not realistic inside one trade window
MIN_P_TARGET = 0.20     # a plan whose target comes first in under 20% of replays is not a plan


def candidates(direction, price, atr, lvls, cfg_risk):
    long = direction == "LONG"
    sgn = 1 if long else -1
    prices = [l["price"] for l in lvls]
    # entries
    entries = [(price, "live price")]
    helpful = [l for l in lvls if (l["price"] < price if long else l["price"] > price) and abs(l["price"] - price) <= 0.6 * atr]
    if helpful:
        h = max(helpful, key=lambda l: l["price"]) if long else min(helpful, key=lambda l: l["price"])
        entries.append((h["price"] + sgn * 0.05 * atr, f"limit just {'above' if long else 'below'} {h['label']}"))
    out = []
    for e, e_why in entries:
        stops = []
        for l in lvls:
            if (l["price"] < e if long else l["price"] > e):
                s = l["price"] - sgn * 0.15 * atr
                stops.append((s, f"just beyond {l['label']}"))
        for m in (1.0, 1.5, 2.0):
            stops.append((e - sgn * m * atr, f"{m:g}x ATR"))
        stops = [(s, w) for s, w in stops if cfg_risk["min_stop_atr"] * atr <= abs(e - s) <= 3 * atr]
        for s, s_why in stops:
            risk = abs(e - s)
            tgts = [(l["price"] - sgn * 0.1 * atr, f"just before {l['label']}") for l in lvls if (l["price"] > e if long else l["price"] < e)]
            tgts += [(e + sgn * k * risk, f"{k:g}R") for k in (1.5, 2, 3)]
            # realistic targets only: at least 1.2R, at most MAX_TARGET_ATR ATR away, nearest 5 levels
            tgts = sorted([(t, w) for t, w in tgts if abs(t - e) / risk >= 1.2 and abs(t - e) <= MAX_TARGET_ATR * atr],
                          key=lambda x: abs(x[0] - e))[:5]
            for t, t_why in tgts:
                out.append({"entry": round(e, 6), "stop": round(s, 6), "target": round(t, 6),
                            "why": {"entry": e_why, "stop": s_why, "target": t_why}})
    # de-duplicate near-identical plans
    seen, uniq = set(), []
    for c in out:
        key = (round(c["entry"] / (0.05 * atr)), round(c["stop"] / (0.05 * atr)), round(c["target"] / (0.05 * atr)))
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq


def optimize(symbol, market, direction, style="intraday", folder=None):
    cfg = desk.config()
    market, data_sym, display = md.detect(symbol, market)
    lv = desk.load(os.path.join(folder, "levels.json")) if folder else None
    if not lv:
        lv = levels_mod.compute(display, market, style)
        if folder:
            desk.save(os.path.join(folder, "levels.json"), lv)
    price, atr = lv["price"], lv["atr"]
    long = direction == "LONG"
    pip = desk.pip_size(market, data_sym)
    rmin = cfg["risk"]["min_reward_risk_after_costs"]
    cands = candidates(direction, price, atr, lv["levels"], cfg["risk"])
    passing = []
    for c in cands:
        c_stop, _ = desk.round_trip_cost(market, style, long, c["entry"], c["stop"], 1.0, cfg["costs"], pip)
        c_tgt, _ = desk.round_trip_cost(market, style, long, c["entry"], c["target"], 1.0, cfg["costs"], pip)
        r_net = (abs(c["target"] - c["entry"]) - c_tgt) / (abs(c["entry"] - c["stop"]) + c_stop)
        c["r_after_costs"] = round(r_net, 3)
        c["stop_in_atr"] = round(abs(c["entry"] - c["stop"]) / atr, 2)
        if r_net >= rmin:
            passing.append(c)
    result = {"computed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "symbol": display, "market": market,
              "style": style, "direction": direction, "price": price, "atr": atr, "candidates_tried": len(cands),
              "passed_cost_rule": len(passing), "replays_each": REPLAYS}
    if not passing:
        result.update({"best": [], "status": "NO_PLAN",
                       "plain": f"None of the {len(cands)} plans built from real levels pays at least {rmin}x the risk after costs. "
                                "The nearby floors and ceilings are too close together for this trade right now."})
        return result
    ctx = tm.prepare(display, market, style)
    for c in passing:
        mc, _, lean, _ = tm.run_plan(ctx, direction, c["entry"], c["stop"], [c["target"]], REPLAYS, 19, with_history=False)
        c.update({"p_target": mc["p_target"], "p_stop": mc["p_stop"], "p_neither": mc["p_neither"], "avg_R": mc["avg_R"], "lean": lean})
    blocked = set(cfg["risk"]["block_timemachine_lean"]) | set(cfg["risk"]["warn_timemachine_lean"])
    ok = sorted([c for c in passing if c["lean"] not in blocked and c["p_target"] >= MIN_P_TARGET * 0.8],
                key=lambda c: c["avg_R"], reverse=True)
    for c in ok[:3]:  # full check with real history for the finalists
        mc, hist, lean, line = tm.run_plan(ctx, direction, c["entry"], c["stop"], [c["target"]], 10000, 19)
        c.update({"p_target": mc["p_target"], "p_stop": mc["p_stop"], "p_neither": mc["p_neither"], "avg_R": mc["avg_R"], "lean": lean,
                  "verdict": line, "history": {k: hist[k] for k in ("samples", "target", "stop", "neither")}})
    ok = sorted(ok[:3], key=lambda c: c["avg_R"], reverse=True)
    good = [c for c in ok if c["avg_R"] > 0 and c["lean"] not in blocked and c["p_target"] >= MIN_P_TARGET]
    if good:
        b = good[0]
        status = "PLAN_FOUND"
        plain = (f"Best plan found by code: {'buy' if long else 'sell'} at {b['entry']:g} ({b['why']['entry']}), safety exit {b['stop']:g} "
                 f"({b['why']['stop']}), target {b['target']:g} ({b['why']['target']}). It pays {b['r_after_costs']}x the risk after costs; "
                 f"in 10,000 replays the target came first {b['p_target']:.0%} vs the stop {b['p_stop']:.0%} (average {b['avg_R']:+.2f}R).")
    else:
        status = "NO_EDGE"
        best_pt = max(c["p_target"] for c in passing)
        plain = (f"{len(passing)} plans pay enough on paper, but none passes the odds test: reach the target first at least "
                 f"{MIN_P_TARGET:.0%} of the time, not lean toward the stop, and make money on average in the replays "
                 f"(best target-first chance {best_pt:.0%}, best average {max(c['avg_R'] for c in passing):+.2f}R). The odds do not favour this trade right now.")
    result.update({"status": status, "plain": plain, "best": ok[:3], "notes": ctx["notes"]})
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?")
    ap.add_argument("--symbol"); ap.add_argument("--market", default="auto")
    ap.add_argument("--direction"); ap.add_argument("--style", default="intraday")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if a.folder:
        folder = os.path.abspath(a.folder)
        meta = desk.load(os.path.join(folder, "meta.json"), {})
        snap = desk.load(os.path.join(folder, "snapshot.json"), {})
        res = optimize(snap.get("data_symbol") or meta["symbol"], snap.get("market") or meta["market"],
                       meta.get("direction", "LONG").upper(), snap.get("style") or meta.get("style", "intraday"), folder)
        desk.save(os.path.join(folder, "optimizer.json"), res)
        audit(folder, "optimizer", f"{res['status']}: tried {res['candidates_tried']}, {res['passed_cost_rule']} passed costs")
        print(f"wrote optimizer.json: {res['status']}: {res['plain']}")
    else:
        res = optimize(a.symbol, a.market, a.direction.upper(), a.style)
        print(json.dumps({k: v for k, v in res.items()}, indent=2))


if __name__ == "__main__":
    main()
