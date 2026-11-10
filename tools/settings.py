#!/usr/bin/env python3
"""Settings (Y): show, check and safely change config/desk.json.

  python tools/settings.py show                                  # plain-language summary of every setting
  python tools/settings.py check                                 # validates the file; exit 1 on problems
  python tools/settings.py set accounts.nse.capital 200000       # change one value (validated before saving)
  python tools/settings.py set risk.risk_per_trade_pct 0.5

Every change is checked against safe bounds (e.g. risk per trade 0.1-3%, minimum reward-to-risk 1.0-5.0),
saved, and written to docs/settings.json for the dashboard. Nothing else in the file is touched.
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "config", "desk.json")
BOUNDS = {
    "risk.risk_per_trade_pct": (0.1, 3.0), "risk.daily_loss_limit_pct": (0.5, 10.0), "risk.max_trades_per_day": (1, 20),
    "risk.min_reward_risk_after_costs": (1.0, 5.0), "risk.min_stop_atr": (0.5, 3.0), "risk.max_position_pct": (1.0, 100.0),
    "budget.max_debates_per_day": (0, 30), "budget.max_debates_per_scan": (0, 5), "paper.start_capital": (1000, 10 ** 9),
    "paper.risk_per_trade_pct": (0.1, 3.0),
}
CAPITAL_KEYS = [f"accounts.{m}.capital" for m in ("crypto", "us", "nse", "forex")]


def load():
    with open(PATH, encoding="utf-8") as f:
        return json.load(f)


def get(d, path):
    for k in path.split("."):
        d = d[k]
    return d


def put(d, path, value):
    ks = path.split(".")
    for k in ks[:-1]:
        d = d[k]
    if ks[-1] not in d:
        raise KeyError(f"unknown setting {path}")
    d[ks[-1]] = value


def check(cfg):
    errs = []
    for k, (lo, hi) in BOUNDS.items():
        try:
            v = get(cfg, k)
        except KeyError:
            errs.append(f"{k} is missing")
            continue
        if not isinstance(v, (int, float)) or not lo <= v <= hi:
            errs.append(f"{k} = {v} is outside the safe range {lo}-{hi}")
    for k in CAPITAL_KEYS:
        v = get(cfg, k)
        if v is not None and (not isinstance(v, (int, float)) or v <= 0):
            errs.append(f"{k} must be a positive number or null (not set)")
    if cfg["risk"].get("max_loss_per_trade") is not None and cfg["risk"]["max_loss_per_trade"] <= 0:
        errs.append("risk.max_loss_per_trade must be positive or null")
    return errs


def summary(cfg):
    a, r, b = cfg["accounts"], cfg["risk"], cfg["budget"]
    lines = ["Capital per market: " + ", ".join(f"{m} {v['currency']} {v['capital']:,}" if v.get("capital") else f"{m} not set" for m, v in a.items()),
             f"Risk per trade: {r['risk_per_trade_pct']}% of capital" + (f", never more than {r['max_loss_per_trade']}" if r.get("max_loss_per_trade") else ""),
             f"Daily loss limit: {r['daily_loss_limit_pct']}%; max {r['max_trades_per_day']} TAKE calls per day",
             f"A trade must pay at least {r['min_reward_risk_after_costs']}x its risk after costs; stop at least {r['min_stop_atr']}x ATR",
             f"Biggest position: {r['max_position_pct']}% of capital",
             "Shorting allowed: " + ", ".join(k for k, v in r["allow_short"].items() if v) + "; not allowed: " + ", ".join(k for k, v in r["allow_short"].items() if not v),
             f"AI usage: at most {b['max_debates_per_day']} debates a day, {b['max_debates_per_scan']} per scan",
             f"Residence: {cfg['owner'].get('residence')} (forex limited to: {', '.join(cfg['india_forex_allowed_pairs'])})" if cfg["owner"].get("residence") == "IN" else ""]
    return [l for l in lines if l]


def publish(cfg):
    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    with open(os.path.join(ROOT, "docs", "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"summary": summary(cfg), "capital_set": {m: bool(v.get("capital")) for m, v in cfg["accounts"].items()}}, f, indent=2)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    cfg = load()
    if cmd == "show":
        for l in summary(cfg):
            print("-", l)
        publish(cfg)
    elif cmd == "check":
        errs = check(cfg)
        print("OK" if not errs else "\n".join("PROBLEM: " + e for e in errs))
        sys.exit(1 if errs else 0)
    elif cmd == "set" and len(sys.argv) == 4:
        path, raw = sys.argv[2], sys.argv[3]
        value = None if raw.lower() in ("null", "none", "unset") else json.loads(raw) if raw.lower() in ("true", "false") else float(raw) if any(c in raw for c in ".eE") else int(raw) if raw.lstrip("-").isdigit() else raw
        old = get(cfg, path)
        put(cfg, path, value)
        errs = check(cfg)
        if errs:
            print("NOT SAVED: " + "; ".join(errs))
            sys.exit(1)
        with open(PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.write("\n")
        publish(cfg)
        print(f"saved {path}: {old} -> {value}")
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
