#!/usr/bin/env python3
"""The trading desk: everything a careful trader does before pressing buy, done in code.

Rule of this project: the AI agents ARGUE, this file CALCULATES. Every number the money depends on
(reward-to-risk, distances in ATR, costs, position size, limits) comes from here, never from a model.

  python tools/desk.py analyze debates/<id> --round N   # after each round: check Bull's plan + Time Machine odds
                                                         #   -> debates/<id>/desk_rN.json
  python tools/desk.py gate debates/<id>                 # after the Judge: fresh price, costs, size, risk gate,
                                                         #   plain-language ticket -> debates/<id>/desk_final.json
  python tools/desk.py check --market crypto --symbol ETH --direction LONG --entry 2068 --stop 2047 --target 2096
                                                         # one-off check of any plan, printed

Settings: config/desk.json (capital, risk limits, broker costs). Nothing here places orders.
"""
import argparse, json, math, os, re, sys, urllib.parse
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import market_data  # noqa: E402
import events as events_mod  # noqa: E402
import timemachine  # noqa: E402

NUM = re.compile(r"-?\d[\d,]*\.?\d*")


# ---------------------------------------------------------------- helpers
def now_utc():
    return datetime.now(timezone.utc)


def iso(dt=None):
    return (dt or now_utc()).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def config():
    cfg = load(os.path.join(ROOT, "config", "desk.json"))
    if not cfg:
        raise SystemExit("config/desk.json is missing or not valid JSON")
    return cfg


def num(v):
    """'2,066-2,070' -> 2068.0 (midpoint of a zone); '74,100' -> 74100.0; 1.12 -> 1.12; junk -> None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    xs = [float(x.replace(",", "")) for x in NUM.findall(str(v)) if x.replace(",", "").replace(".", "").replace("-", "")]
    xs = [abs(x) for x in xs]
    if not xs:
        return None
    return (xs[0] + xs[1]) / 2 if len(xs) >= 2 and re.search(r"\d\s*[-–to]+\s*\d", str(v)) else xs[0]


def plan_from(d, fallback_direction="LONG"):
    """Accept {'plan_numbers': {...}} or {'trade_plan_numbers': {...}} or a text plan; return numeric plan or None."""
    if not d:
        return None
    p = d.get("plan_numbers") or d.get("trade_plan_numbers") or d.get("plan") or d.get("trade_plan") or {}
    direction = str(p.get("direction") or fallback_direction).upper()
    entry = num(p.get("entry"))
    stop = num(p.get("stop") if p.get("stop") is not None else p.get("stop_loss"))
    tg = p.get("targets") or []
    if not isinstance(tg, list):
        tg = [tg]
    targets = [x for x in (num(t) for t in tg) if x]
    if not (entry and stop and targets):
        return None
    return {"direction": "SHORT" if direction.startswith("SHORT") else "LONG", "entry": entry, "stop": stop, "targets": targets}


def atr_for(snapshot, style):
    tfs = [t for t in snapshot.get("timeframes", []) if not t.get("error")]
    want = "1d" if style == "swing" else "1h"
    for t in tfs:
        if t.get("timeframe") == want:
            return t.get("atr14"), want
    return (tfs[-1].get("atr14"), tfs[-1].get("timeframe")) if tfs else (None, None)


def instrument_currency(market, data_symbol):
    if market == "nse":
        return "INR"
    if market == "forex":
        return data_symbol.replace("=X", "")[3:6]
    return "USD"  # crypto is quoted in USDT, treated as USD; US stocks in USD


def pip_size(market, data_symbol):
    return 0.01 if market == "forex" and data_symbol.replace("=X", "")[3:6] == "JPY" else 0.0001


_fx_cache = {}


def fx_rate(src, dst):
    """1 unit of src in dst, from Yahoo (e.g. USD->INR). Same currency -> 1."""
    if src == dst:
        return 1.0
    key = src + dst
    if key not in _fx_cache:
        d = market_data.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{key}=X?interval=1d&range=5d")
        _fx_cache[key] = float(d["chart"]["result"][0]["meta"]["regularMarketPrice"])
    return _fx_cache[key]


def crypto_rules(data_symbol):
    try:
        d = market_data.binance(f"/api/v3/exchangeInfo?symbol={data_symbol}")
        f = {x["filterType"]: x for x in d["symbols"][0]["filters"]}
        step = float(f["LOT_SIZE"]["stepSize"])
        mn = float((f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}).get("minNotional", 5))
        return step, mn
    except Exception:
        return 0.0001, 5.0


def floor_step(x, step):
    if step <= 0:
        return x
    n = math.floor(x / step + 1e-9)
    decimals = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
    return round(n * step, decimals)


# ---------------------------------------------------------------- 1. plan check (pure)
def plan_check(plan, price, atr, atr_tf, market, cfg_risk):
    long = plan["direction"] == "LONG"
    e, s, ts = plan["entry"], plan["stop"], plan["targets"]
    issues = []
    risk = (e - s) if long else (s - e)
    if risk <= 0:
        issues.append({"level": "block", "id": "stop_side", "plain": "The safety exit (stop-loss) is on the wrong side of the entry price."})
    bad_t = [t for t in ts if ((t <= e) if long else (t >= e))]
    if bad_t:
        issues.append({"level": "block", "id": "target_side", "plain": "A profit target is on the wrong side of the entry price."})
    risk = abs(risk) or 1e-12
    rewards = [abs(t - e) for t in ts]
    rs = [round(r / risk, 3) for r in rewards]
    facts = {
        "direction": plan["direction"], "entry": e, "stop": s, "targets": ts,
        "risk_per_unit": round(risk, 8), "reward_per_unit": [round(r, 8) for r in rewards],
        "r_multiple_gross": rs,
        "stop_distance_pct": round(risk / e * 100, 3),
        "live_price": price,
        "entry_distance_pct": round((e - price) / price * 100, 3) if price else None,
        "atr": atr, "atr_timeframe": atr_tf,
        "stop_in_atr": round(risk / atr, 2) if atr else None,
        "entry_distance_in_atr": round(abs(e - price) / atr, 2) if atr and price else None,
    }
    if atr and facts["stop_in_atr"] is not None and facts["stop_in_atr"] < cfg_risk["min_stop_atr"]:
        issues.append({"level": "warn", "id": "stop_tight",
                       "plain": f"The stop is only {facts['stop_in_atr']}x the normal {atr_tf} move (ATR {atr}). Normal wiggles could hit it."})
    if atr and facts["entry_distance_in_atr"] is not None and facts["entry_distance_in_atr"] > cfg_risk["max_entry_distance_atr"]:
        issues.append({"level": "warn", "id": "entry_far",
                       "plain": f"The entry is {facts['entry_distance_in_atr']}x ATR away from the live price ({price}); it may never fill."})
    return facts, issues


# ---------------------------------------------------------------- 2. costs (pure)
def round_trip_cost(market, style, long, entry, exit_price, qty, costs, pip=0.0001):
    """Total cost in the instrument's currency to open AND close qty units. Returns (amount, breakdown)."""
    buy_px, sell_px = (entry, exit_price) if long else (exit_price, entry)
    buy_val, sell_val = buy_px * qty, sell_px * qty
    b = {}
    if market == "crypto":
        c = costs["crypto"]
        b["exchange_fees"] = (buy_val + sell_val) * c["fee_pct_per_side"] / 100
        b["slippage"] = (buy_val + sell_val) * c["slippage_pct_per_side"] / 100
    elif market == "us":
        c = costs["us"]
        b["commission"] = 2 * c["commission_per_order"]
        b["sec_fee"] = sell_val * c["sec_fee_pct_on_sell"] / 100
        b["slippage"] = (buy_val + sell_val) * c["slippage_pct_per_side"] / 100
    elif market == "nse":
        c = costs["nse_swing" if style == "swing" else "nse_intraday"]
        brk = sum(min(v * c["brokerage_pct"] / 100, c["brokerage_cap_per_order"]) if c["brokerage_cap_per_order"] else v * c["brokerage_pct"] / 100
                  for v in (buy_val, sell_val))
        txn = (buy_val + sell_val) * c["exchange_txn_pct"] / 100
        sebi = (buy_val + sell_val) * c["sebi_pct"] / 100
        b["brokerage"] = brk
        b["stt"] = sell_val * c.get("stt_pct_sell", 0) / 100 + buy_val * c.get("stt_pct_buy", 0) / 100
        b["exchange_txn"] = txn
        b["sebi"] = sebi
        b["stamp_duty"] = buy_val * c["stamp_pct_buy"] / 100
        b["gst"] = (brk + txn + sebi) * c["gst_pct"] / 100
        b["dp_charge"] = c.get("dp_charge_per_sell", 0)
        b["slippage"] = (buy_val + sell_val) * c["slippage_pct_per_side"] / 100
    elif market == "forex":
        c = costs["forex"]
        b["spread"] = c["spread_pips"] * pip * qty
        b["slippage"] = 2 * c["slippage_pips"] * pip * qty
        b["commission_inr_converted_later"] = 0.0  # fixed per-order fee is in account currency, added in size()
    total = sum(b.values())
    return total, {k: round(v, 4) for k, v in b.items()}


# ---------------------------------------------------------------- 3. size
def size(plan, market, style, data_symbol, cfg, day_volume=None, quote_volume_usd=None):
    """Quantity that keeps (loss at stop + costs) inside the per-trade risk budget, then capped."""
    acct = cfg["accounts"][market]
    capital = acct.get("capital")
    risk_cfg = cfg["risk"]
    inst = instrument_currency(market, data_symbol)
    long = plan["direction"] == "LONG"
    e, s, t1 = plan["entry"], plan["stop"], plan["targets"][0]
    per_unit_risk = abs(e - s)
    pip = pip_size(market, data_symbol)
    out = {"account_currency": acct["currency"], "instrument_currency": inst, "capital": capital, "notes": []}
    try:
        rate = fx_rate(inst, acct["currency"])
    except Exception:
        rate = None
        out["notes"].append(f"Could not fetch the {inst}->{acct['currency']} rate; money amounts shown in {inst}.")
    out["fx_rate"] = rate
    conv = rate or 1.0
    fixed_fee = 2 * cfg["costs"]["forex"]["commission_per_order"] if market == "forex" else 0.0  # account ccy
    # cost per unit at the stop and at target 1 (linear part only)
    c_stop, _ = round_trip_cost(market, style, long, e, s, 1.0, cfg["costs"], pip)
    c_tgt, _ = round_trip_cost(market, style, long, e, t1, 1.0, cfg["costs"], pip)
    if not capital:
        out.update({"status": "NO_CAPITAL", "qty": None,
                    "per_unit_loss_at_stop": round((per_unit_risk + c_stop) * conv, 6),
                    "per_unit_gain_at_target1": round((abs(t1 - e) - c_tgt) * conv, 6)})
        out["notes"].append("Capital is not set in config/desk.json, so no position size was calculated.")
        return out
    budget = capital * risk_cfg["risk_per_trade_pct"] / 100
    if risk_cfg.get("max_loss_per_trade"):
        budget = min(budget, risk_cfg["max_loss_per_trade"])
    budget_inst = (budget - fixed_fee) / conv
    if market == "crypto":
        step, min_notional = crypto_rules(data_symbol)
    elif market == "forex":
        step, min_notional = cfg["sizing"]["forex_unit_step"], 0.0
    else:
        step, min_notional = 1.0, 0.0
    qty = floor_step(max(budget_inst, 0) / (per_unit_risk + c_stop), step)
    limiter = "risk per trade"
    # position cap
    cap_val = capital * risk_cfg["max_position_pct"] / 100 / conv
    if market != "forex" and qty * e > cap_val:
        qty, limiter = floor_step(cap_val / e, step), f"max position {risk_cfg['max_position_pct']}% of capital"
    # NSE fixed charges (brokerage cap, DP) are not linear: re-check the real loss at the stop
    for _ in range(50):
        total_stop, _b = round_trip_cost(market, style, long, e, s, qty, cfg["costs"], pip)
        loss = (per_unit_risk * qty + total_stop) * conv + fixed_fee
        if loss <= budget + 1e-9 or qty <= 0:
            break
        qty = floor_step(qty - step, step)
    total_stop, br_stop = round_trip_cost(market, style, long, e, s, qty, cfg["costs"], pip)
    total_t1, br_t1 = round_trip_cost(market, style, long, e, t1, qty, cfg["costs"], pip)
    loss_at_stop = (per_unit_risk * qty + total_stop) * conv + fixed_fee
    gain_at_t1 = (abs(t1 - e) * qty - total_t1) * conv - fixed_fee
    out.update({
        "status": "OK" if qty > 0 else "TOO_SMALL", "qty": qty, "qty_step": step, "limited_by": limiter,
        "risk_budget": round(budget, 2), "position_value": round(qty * e * conv, 2),
        "loss_at_stop_incl_costs": round(loss_at_stop, 2), "gain_at_target1_after_costs": round(gain_at_t1, 2),
        "costs_round_trip_at_stop": round(total_stop * conv + fixed_fee, 2), "cost_breakdown_at_stop": br_stop,
        "r_after_costs_target1": round(gain_at_t1 / loss_at_stop, 3) if loss_at_stop > 0 else None,
    })
    if qty > 0 and min_notional and qty * e < min_notional:
        out["status"] = "TOO_SMALL"
        out["notes"].append(f"Order value {qty * e:.2f} is below the exchange minimum ({min_notional}).")
    if qty > 0 and day_volume and market in ("us", "nse") and qty > day_volume * risk_cfg["max_share_of_day_volume_pct"] / 100:
        out["notes"].append("This order would be a large share of today's trading volume; fills may be poor.")
    return out


# ---------------------------------------------------------------- 4. risk gate (pure-ish)
def risk_gate(plan, facts, plan_issues, sz, snap, ev, tm, market, style, data_symbol, cfg, trades_today):
    r = cfg["risk"]
    checks = []

    def add(cid, level, plain):
        checks.append({"id": cid, "level": level, "plain": plain})

    for i in plan_issues:
        add(i["id"], i["level"], i["plain"])
    long = plan["direction"] == "LONG"
    # shorting allowed?
    if not long:
        key = f"nse_{style}" if market == "nse" else market
        if not r["allow_short"].get(key, False):
            add("short_not_allowed", "block", {
                "crypto": "This is a SHORT trade. Spot crypto cannot be shorted; it needs futures or margin, which your settings do not allow.",
                "us": "This is a SHORT trade. Shorting US stocks needs a margin account, which your settings do not allow.",
                "nse_swing": "This is a SHORT trade held for days. NSE cash shares can only be shorted intraday; a multi-day short needs futures.",
            }.get(key, "Your settings do not allow SHORT trades in this market."))
    # India: legal forex
    if market == "forex" and cfg["owner"].get("residence") == "IN":
        pair = data_symbol.replace("=X", "")
        if pair not in cfg["india_forex_allowed_pairs"]:
            add("forex_jurisdiction", "block",
                f"{pair[:3]}/{pair[3:]} is not one of the pairs Indian residents may trade. Under RBI/FEMA rules, residents can trade only "
                "INR pairs and EUR/USD, GBP/USD, USD/JPY, and only as exchange-traded contracts on NSE/BSE, not with overseas forex brokers.")
        else:
            add("forex_jurisdiction", "pass", "Allowed pair for Indian residents, as an NSE/BSE currency-derivative contract only.")
    # market open + data age (intraday)
    status = str(snap.get("market_status", ""))
    if style == "intraday" and not status.startswith("OPEN"):
        add("market_closed", "block", f"The market is closed right now ({status}). An intraday trade cannot start.")
    tfs = [t for t in snap.get("timeframes", []) if not t.get("error")]
    if style == "intraday" and tfs:
        last = datetime.fromisoformat(tfs[0]["last_candle_utc"].replace("Z", "+00:00"))
        age = (now_utc() - last).total_seconds() / 60
        if age > r["max_data_age_minutes_intraday"] and status.startswith("OPEN"):
            add("stale_data", "block", f"The newest price data is {age:.0f} minutes old. Too old to trade on.")
    # events
    if ev:
        lvl = {"BLOCK": "block", "CAUTION": "warn"}.get(ev.get("status"), "pass")
        add("event_guard", lvl, ev.get("plain", ""))
    # time machine
    if tm and tm.get("lean"):
        lvl = "block" if tm["lean"] in r["block_timemachine_lean"] else "warn" if tm["lean"] in r["warn_timemachine_lean"] else "pass"
        add("time_machine", lvl, tm.get("verdict", ""))
    # reward to risk after costs
    rr = sz.get("r_after_costs_target1")
    basis = "after costs"
    if rr is None and sz.get("per_unit_loss_at_stop"):
        rr = round(sz["per_unit_gain_at_target1"] / sz["per_unit_loss_at_stop"], 3)
        basis = "after costs (per unit; fixed per-order fees not included until capital is set)"
    elif rr is None and facts.get("r_multiple_gross"):
        rr = facts["r_multiple_gross"][0]
        basis = "before costs"
    if rr is not None:
        if rr < r["min_reward_risk_after_costs"]:
            add("reward_risk", "block", f"The first target pays {rr:.2f}x the risk {basis}; your minimum is {r['min_reward_risk_after_costs']}x.")
        else:
            add("reward_risk", "pass", f"The first target pays {rr:.2f}x the risk {basis}.")
    # sizing
    if sz.get("status") == "NO_CAPITAL":
        add("capital_not_set", "warn", "Your capital for this market is not set, so the position size could not be checked.")
    elif sz.get("status") == "TOO_SMALL":
        add("size_too_small", "block", "With your risk limit, the position would be smaller than the smallest allowed order.")
    for n in sz.get("notes", []):
        if "volume" in n:
            add("liquidity", "warn", n)
    # daily trade count
    if trades_today >= r["max_trades_per_day"]:
        add("max_trades", "block", f"You already have {trades_today} TAKE tickets today; your limit is {r['max_trades_per_day']}.")
    overall = "BLOCK" if any(c["level"] == "block" for c in checks) else "PASS"
    return overall, checks


def fmt(x, nd=None):
    if x is None:
        return "?"
    if nd is None:
        nd = 2 if abs(x) >= 100 else 4 if abs(x) >= 1 else 6
    return f"{x:,.{nd}f}"


def ticket_plain(plan, sz, market, display, broker):
    long = plan["direction"] == "LONG"
    side = "BUY" if long else "SELL (short)"
    exit_side = "sell" if long else "buy back"
    unit = {"crypto": display.split("/")[0], "us": "shares", "nse": "shares", "forex": "units"}[market]
    q = f"{sz['qty']} {unit}" if sz.get("qty") else f"[set your capital to size this] {unit}"
    lines = [
        f"{side} {q} of {display} near {fmt(plan['entry'])} (use a limit order, not market).",
        f"Safety exit: if the price reaches {fmt(plan['stop'])}, {exit_side} everything (stop-loss order).",
        "Take profit: " + ", then ".join(fmt(t) for t in plan["targets"]) + ".",
    ]
    if sz.get("qty"):
        cur = sz["account_currency"]
        lines.append(f"If the stop is hit you lose about {cur} {sz['loss_at_stop_incl_costs']:,.2f} including costs; "
                     f"at the first target you make about {cur} {sz['gain_at_target1_after_costs']:,.2f} after costs.")
    lines.append(f"Place it yourself in {broker or 'your broker'}. This tool never places orders.")
    return lines


# ---------------------------------------------------------------- commands
def debate_ctx(folder):
    meta = load(os.path.join(folder, "meta.json"), {})
    snap = load(os.path.join(folder, "snapshot.json"), {})
    market, data_symbol, display = market_data.detect(snap.get("data_symbol") or meta.get("symbol"), snap.get("market") or meta.get("market") or "auto")
    style = snap.get("style") or meta.get("style") or "intraday"
    return meta, snap, market, data_symbol, display, style


def ensure_events(folder, market, display, style, refresh=False):
    path = os.path.join(folder, "events.json")
    ev = None if refresh else load(path)
    if not ev:
        ev = events_mod.guard(market, display, style)
        save(path, ev)
    return ev


def run_tm(plan, market, display, style):
    try:
        return timemachine.run(display, market, plan["direction"], plan["entry"], plan["stop"], plan["targets"], style)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def tm_brief(tm):
    if not tm or tm.get("error"):
        return tm
    return {k: tm[k] for k in ("plan", "data", "mc", "history", "lean", "verdict", "plain", "notes", "caveat")}


def cmd_analyze(folder, rnd):
    cfg = config()
    meta, snap, market, data_symbol, display, style = debate_ctx(folder)
    bull = load(os.path.join(folder, f"r{rnd}_bull.json"))
    plan = plan_from(bull, meta.get("direction", "LONG"))
    ev = ensure_events(folder, market, display, style)
    out = {"round": rnd, "computed_utc": iso(), "plan_source": f"r{rnd}_bull.json", "plan": plan, "events": ev}
    if not plan:
        out["error"] = "Bull's plan has no usable entry / stop / target numbers."
    else:
        atr, tf = atr_for(snap, style)
        fresh = market_data.build(display, market, style, with_news=False)
        facts, issues = plan_check(plan, fresh.get("price"), atr, tf, market, cfg["risk"])
        out.update({"plan_check": facts, "plan_issues": issues, "timemachine": tm_brief(run_tm(plan, market, display, style))})
    save(os.path.join(folder, f"desk_r{rnd}.json"), out)
    tm = out.get("timemachine") or {}
    print(f"wrote desk_r{rnd}.json: plan={plan} | TM: {tm.get('verdict') or tm.get('error')} | events: {ev['status']}")


def trades_today(cfg, exclude=None):
    off = cfg["owner"].get("utc_offset_minutes", 0) * 60
    today = datetime.fromtimestamp(now_utc().timestamp() + off, timezone.utc).date()
    n = 0
    base = os.path.join(ROOT, "debates")
    for d in os.listdir(base) if os.path.isdir(base) else []:
        f = load(os.path.join(base, d, "desk_final.json"))
        if not f or d == exclude or f.get("final_call") != "TAKE":
            continue
        t = datetime.fromisoformat(f["computed_utc"].replace("Z", "+00:00"))
        if datetime.fromtimestamp(t.timestamp() + off, timezone.utc).date() == today:
            n += 1
    return n


def cmd_gate(folder):
    cfg = config()
    meta, snap, market, data_symbol, display, style = debate_ctx(folder)
    verdict = load(os.path.join(folder, "verdict.json"), {})
    judge = str(verdict.get("decision", "SKIP")).upper()
    plan = plan_from(verdict, meta.get("direction", "LONG"))
    if not plan:
        last = load(os.path.join(folder, "r3_bull.json")) or load(os.path.join(folder, "r2_bull.json")) or load(os.path.join(folder, "r1_bull.json"))
        plan = plan_from(last, meta.get("direction", "LONG"))
    out = {"computed_utc": iso(), "judge_decision": judge, "plan": plan}
    if not plan:
        out.update({"gate": "BLOCK", "final_call": "SKIP", "checks": [{"id": "no_plan", "level": "block", "plain": "No usable trade plan numbers were found."}]})
        save(os.path.join(folder, "desk_final.json"), out)
        print("wrote desk_final.json: no plan")
        return
    fresh = market_data.build(display, market, style, with_news=False)
    atr, tf = atr_for(fresh, style)
    facts, issues = plan_check(plan, fresh.get("price"), atr, tf, market, cfg["risk"])
    ev = ensure_events(folder, market, display, style, refresh=True)
    r3 = load(os.path.join(folder, "desk_r3.json"), {})
    tm = r3.get("timemachine") if r3.get("plan") == plan else None
    tm = tm or tm_brief(run_tm(plan, market, display, style))
    day_vol = fresh.get("day_volume")
    sz = size(plan, market, style, data_symbol, cfg, day_volume=day_vol, quote_volume_usd=fresh.get("quote_volume_24h_usdt"))
    gate, checks = risk_gate(plan, facts, issues, sz, fresh, ev, tm if tm and not tm.get("error") else None,
                             market, style, data_symbol, cfg, trades_today(cfg, exclude=os.path.basename(folder.rstrip("/\\"))))
    final = "TAKE" if judge in ("TAKE", "BUY") and gate == "PASS" else "SKIP"
    blocks = [c["plain"] for c in checks if c["level"] == "block"]
    if judge in ("TAKE", "BUY") and gate == "BLOCK":
        summary = "The Judge said TAKE, but the risk manager BLOCKED it: " + blocks[0]
    elif final == "TAKE":
        summary = "The Judge said TAKE and every risk check passed."
    else:
        summary = "The Judge said SKIP." + (f" The risk manager agrees: {blocks[0]}" if blocks else " The risk checks found no hard blocks.")
    out.update({
        "price_at_gate": fresh.get("price"), "market_status": fresh.get("market_status"),
        "plan_check": facts, "sizing": sz, "events": {k: ev[k] for k in ("status", "plain", "events", "notes")},
        "timemachine": tm, "gate": gate, "checks": checks, "final_call": final, "summary_plain": summary,
        "ticket_plain": ticket_plain(plan, sz, market, display, cfg["accounts"][market].get("broker")) if final == "TAKE" else None,
    })
    save(os.path.join(folder, "desk_final.json"), out)
    print(f"wrote desk_final.json: judge={judge} gate={gate} final={final} | {summary}")


def cmd_check(a):
    cfg = config()
    market, data_symbol, display = market_data.detect(a.symbol, a.market)
    plan = {"direction": a.direction.upper(), "entry": a.entry, "stop": a.stop, "targets": a.target}
    fresh = market_data.build(display, market, a.style, with_news=False)
    atr, tf = atr_for(fresh, a.style)
    facts, issues = plan_check(plan, fresh.get("price"), atr, tf, market, cfg["risk"])
    sz = size(plan, market, a.style, data_symbol, cfg, fresh.get("day_volume"))
    ev = events_mod.guard(market, display, a.style)
    tm = tm_brief(run_tm(plan, market, display, a.style))
    gate, checks = risk_gate(plan, facts, issues, sz, fresh, ev, tm if not tm.get("error") else None, market, a.style, data_symbol, cfg, 0)
    print(json.dumps({"plan_check": facts, "sizing": sz, "gate": gate, "checks": checks,
                      "timemachine": {k: tm.get(k) for k in ("lean", "verdict", "plain")} if tm else None}, indent=2))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("analyze"); p.add_argument("folder"); p.add_argument("--round", type=int, required=True)
    p = sub.add_parser("gate"); p.add_argument("folder")
    p = sub.add_parser("check")
    p.add_argument("--market", default="auto"); p.add_argument("--symbol", required=True); p.add_argument("--style", default="intraday")
    p.add_argument("--direction", required=True); p.add_argument("--entry", type=float, required=True)
    p.add_argument("--stop", type=float, required=True); p.add_argument("--target", type=float, action="append", required=True)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if a.cmd == "analyze":
        cmd_analyze(os.path.abspath(a.folder), a.round)
    elif a.cmd == "gate":
        cmd_gate(os.path.abspath(a.folder))
    else:
        cmd_check(a)


if __name__ == "__main__":
    main()
