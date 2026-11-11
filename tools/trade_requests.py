#!/usr/bin/env python3
"""Your own trades, queued for the next scan ("Add my trade" on the dashboard).

The dashboard form creates one small file per request in `requests/` (you commit it on GitHub,
so nothing secret is ever stored in the page). The scheduled scan debates these FIRST.

  python tools/trade_requests.py list            # JSON: requests ready to debate now (+ the ones still waiting, with why)
  python tools/trade_requests.py done FILE --id DEBATE_ID      # debated: move to requests/done/
  python tools/trade_requests.py done FILE --error "reason"    # could not be debated: move with the reason
  python tools/trade_requests.py status          # writes docs/requests.json for the dashboard

Request file (requests/<anything>.json):
  {"symbol": "RELIANCE", "market": "nse", "direction": "LONG", "style": "swing",
   "entry": 1310, "stop": 1285, "target": 1370, "note": "my view", "asked_utc": "2026-11-11T09:00:00Z"}
Only symbol is required. market defaults to auto-detect, direction LONG, style intraday.
Prices are optional, but if you give any of them you must give all three.

Timing: a swing request is debated at the next scan. An intraday request waits for its market to open.
A request that could not be debated within 48 hours expires (moved to done/ with the reason).
"""
import argparse, glob, json, os, re, shutil, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REQ = os.path.join(ROOT, "requests")
DONE = os.path.join(REQ, "done")
sys.path.insert(0, HERE)

EXPIRE_HOURS = 48
METAL_MSG = 'Gold and silver against the dollar (XAU/USD, XAG/USD) are not covered: Indian residents may not trade them with forex brokers, and the desk has no MCX data. To trade gold, add GOLDBEES (a gold ETF) with market NSE; for silver, SILVERBEES.'
MARKETS = ("crypto", "us", "nse", "forex", "auto")


def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def load(p, default=None):
    try:
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def save(p, o):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(o, f, indent=2, ensure_ascii=False)


def _num(v):
    if v in (None, ""):
        return None
    if isinstance(v, bool):
        raise ValueError
    x = float(str(v).replace(",", ""))
    if not (x > 0):
        raise ValueError
    return x


def parse(raw):
    """Clean one request. Returns (request, None) or (None, plain reason it is invalid)."""
    if not isinstance(raw, dict):
        return None, "The file is not a request (it must be a JSON object)."
    sym = str(raw.get("symbol") or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-/=&]{0,19}", sym):
        return None, "The symbol is missing or has characters a ticker cannot have."
    if re.match(r"(XAU|XAG|XPT|XPD)", sym.replace("/", "")) or sym in ("GOLD", "SILVER"):
        return None, METAL_MSG
    market = str(raw.get("market") or "auto").strip().lower()
    if market not in MARKETS:
        return None, f"Market must be crypto, us, nse or forex (got '{market}')."
    d = str(raw.get("direction") or "LONG").strip().upper()
    d = {"BUY": "LONG", "SELL": "SHORT"}.get(d, d)
    if d not in ("LONG", "SHORT"):
        return None, "Direction must be LONG (buy) or SHORT (sell)."
    style = str(raw.get("style") or "intraday").strip().lower()
    if style not in ("intraday", "swing"):
        return None, "Hold time must be intraday or swing."
    try:
        e, s, t = (_num(raw.get(k)) for k in ("entry", "stop", "target"))
    except (TypeError, ValueError):
        return None, "Entry, stop and target must be positive numbers."
    plan = None
    if any(x is not None for x in (e, s, t)):
        if None in (e, s, t):
            return None, "Give all three prices (entry, stop and target) or none of them."
        ok = (s < e < t) if d == "LONG" else (t < e < s)
        if not ok:
            return None, ("For a LONG (buy) the stop must be below the entry and the target above it."
                          if d == "LONG" else "For a SHORT (sell) the stop must be above the entry and the target below it.")
        plan = {"direction": d, "entry": e, "stop": s, "targets": [t]}
    import market_data as md
    market, data_sym, display = md.detect(sym, market)
    note = str(raw.get("note") or "").strip()[:500] or None
    return {"symbol": sym, "display": display, "data_symbol": data_sym, "market": market, "direction": d, "style": style,
            "user_plan": plan, "user_note": note, "asked_utc": raw.get("asked_utc")}, None


def _asked(r, path):
    try:
        return datetime.fromisoformat(str(r.get("asked_utc")).replace("Z", "+00:00"))
    except Exception:
        return datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)


def pending_files():
    return sorted(glob.glob(os.path.join(REQ, "*.json")))


def move_done(path, extra):
    raw = load(path, {}) if os.path.exists(path) else {}
    if not isinstance(raw, dict):
        raw = {"raw": raw}
    raw.update(extra)
    raw["closed_utc"] = iso(now())
    dst = os.path.join(DONE, os.path.basename(path))
    save(dst, raw)
    os.remove(path)
    return dst


def list_requests(open_fn=None):
    if open_fn is None:
        from watch import market_open as open_fn
    ready, waiting, closed = [], [], []
    cache = {}
    for p in pending_files():
        raw = load(p)
        name = os.path.relpath(p, ROOT).replace("\\", "/")
        if raw is None:
            move_done(p, {"status": "invalid", "reason": "The file is not valid JSON."})
            closed.append({"file": name, "status": "invalid"})
            continue
        r, err = parse(raw)
        if err:
            move_done(p, {"status": "invalid", "reason": err})
            closed.append({"file": name, "status": "invalid", "reason": err})
            continue
        age_h = (now() - _asked(raw, p)).total_seconds() / 3600
        r["file"] = name
        if r["style"] == "intraday":
            if r["market"] not in cache:
                cache[r["market"]] = open_fn(r["market"])
            if not cache[r["market"]]:
                if age_h > EXPIRE_HOURS:
                    why = f"Expired: the market never opened during the {EXPIRE_HOURS} hours after you asked."
                    move_done(p, {"status": "expired", "reason": why})
                    closed.append({"file": name, "status": "expired", "reason": why})
                else:
                    r["wait_reason"] = "Waiting for the market to open (an intraday trade can only start while it is open)."
                    waiting.append(r)
                continue
        ready.append(r)
    return {"ready": ready, "waiting": waiting, "closed_now": closed}


def status():
    out = {"updated_utc": iso(now()), "pending": [], "done": []}
    for p in pending_files():
        raw = load(p) or {}
        r, err = parse(raw)
        out["pending"].append({"file": os.path.basename(p), "symbol": (r or {}).get("display") or raw.get("symbol"),
                               "market": (r or {}).get("market") or raw.get("market"), "direction": (r or {}).get("direction"),
                               "style": (r or {}).get("style"), "asked_utc": raw.get("asked_utc"), "problem": err})
    done = []
    for p in glob.glob(os.path.join(DONE, "*.json")):
        raw = load(p) or {}
        done.append({"file": os.path.basename(p), "symbol": raw.get("symbol"), "direction": raw.get("direction"),
                     "market": raw.get("market"), "status": raw.get("status"), "reason": raw.get("reason"),
                     "debate_id": raw.get("debate_id"), "asked_utc": raw.get("asked_utc"), "closed_utc": raw.get("closed_utc")})
    out["done"] = sorted(done, key=lambda x: x.get("closed_utc") or "", reverse=True)[:15]
    save(os.path.join(ROOT, "docs", "requests.json"), out)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    d = sub.add_parser("done")
    d.add_argument("file")
    g = d.add_mutually_exclusive_group(required=True)
    g.add_argument("--id")
    g.add_argument("--error")
    sub.add_parser("status")
    a = ap.parse_args()
    if a.cmd == "list":
        print(json.dumps(list_requests(), indent=2, ensure_ascii=False))
    elif a.cmd == "done":
        path = a.file if os.path.isabs(a.file) else os.path.join(ROOT, a.file)
        if not os.path.exists(path):
            print(f"no such request: {a.file}", file=sys.stderr)
            sys.exit(1)
        extra = {"status": "debated", "debate_id": a.id} if a.id else {"status": "not_debated", "reason": a.error}
        print("moved to", os.path.relpath(move_done(path, extra), ROOT))
    else:
        s = status()
        print(f"wrote docs/requests.json: {len(s['pending'])} pending, {len(s['done'])} recent done")


if __name__ == "__main__":
    main()
