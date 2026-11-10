#!/usr/bin/env python3
"""Paper portfolio (P): a practice account with fake money that follows the desk.

  python tools/paper.py        # reads every outcome.json -> docs/paper.json (and prints a summary)

Rules: the account starts with config paper.start_capital and risks paper.risk_per_trade_pct of its
CURRENT balance on every final TAKE call, in time order. A trade's result in R (multiples of the risk,
from the outcome tracker) becomes money: +2R at 1% risk = +2% of the balance. Trades that never filled
cost nothing. For comparison it also runs a second account that takes EVERY debated trade, including
the ones the desk skipped, to show what the desk's filtering is worth.
"""
import json, os, sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def account(trades, start, risk_pct):
    bal, peak, max_dd, curve = start, start, 0.0, [{"t": None, "balance": start}]
    for t in trades:
        bal += bal * risk_pct / 100 * t["r"]
        peak = max(peak, bal)
        max_dd = max(max_dd, (peak - bal) / peak * 100)
        curve.append({"t": t["closed"], "balance": round(bal, 2), "id": t["id"], "r": t["r"]})
    wins = sum(1 for t in trades if t["r"] > 0)
    return {"trades": len(trades), "wins": wins, "losses": len(trades) - wins, "balance": round(bal, 2),
            "return_pct": round((bal / start - 1) * 100, 2), "max_drawdown_pct": round(max_dd, 2), "curve": curve}


def run():
    cfg = load(os.path.join(ROOT, "config", "desk.json"))["paper"]
    base = os.path.join(ROOT, "debates")
    rows = []
    for d in sorted(os.listdir(base)):
        o = load(os.path.join(base, d, "outcome.json"))
        if not o or o.get("status") not in ("target", "stop", "expired") or o.get("r") is None:
            continue
        rows.append({"id": d, "call": o.get("call"), "r": o["r"], "closed": o.get("closed_utc") or o.get("window_end_utc") or o.get("checked_utc")})
    rows.sort(key=lambda r: r["closed"] or "")
    desk_acct = account([r for r in rows if r["call"] == "TAKE"], cfg["start_capital"], cfg["risk_per_trade_pct"])
    all_acct = account(rows, cfg["start_capital"], cfg["risk_per_trade_pct"])
    out = {"computed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "currency": cfg["currency"],
           "start_capital": cfg["start_capital"], "risk_per_trade_pct": cfg["risk_per_trade_pct"],
           "desk": desk_acct, "take_everything": all_acct,
           "plain": (f"Practice account following the desk: {desk_acct['trades']} trades, balance {cfg['currency']} {desk_acct['balance']:,.0f} "
                     f"({desk_acct['return_pct']:+.2f}%). If it had taken every debated trade instead: {all_acct['return_pct']:+.2f}%.")}
    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    with open(os.path.join(ROOT, "docs", "paper.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(run()["plain"])
