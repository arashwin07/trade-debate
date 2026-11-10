#!/usr/bin/env python3
"""Guardrails (Z): strict checks on every file an AI agent writes, before anything reads it.

  python tools/validate.py debates/<id>/r2_bull.json     # exit 0 = OK, exit 2 = problems (printed, one per line)
  python tools/validate.py debates/<id>/verdict.json
  python tools/validate.py debates/<id>/r1_result.json

Checks: valid JSON, required fields and types, stance matches the agent, every chat message has text,
evidence indices exist, plan numbers are real numbers on the correct side of the entry, and the entry is
within sane bounds of the live price (catches a typo like 1707 instead of 170.7). Every run is written to
the debate's audit.log.
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from audit import audit  # noqa: E402

MAX_ENTRY_DIST = {"intraday": 0.05, "swing": 0.15}  # entry must be within 5% (intraday) / 15% (swing) of the snapshot price


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) != float("inf")


def check_plan_numbers(p, price, style, where):
    errs = []
    if not isinstance(p, dict):
        return [f"{where} is missing or not an object"]
    d = str(p.get("direction", "")).upper()
    if d not in ("LONG", "SHORT"):
        errs.append(f"{where}.direction must be LONG or SHORT")
    e, s, ts = p.get("entry"), p.get("stop"), p.get("targets")
    if not _num(e) or e <= 0:
        errs.append(f"{where}.entry must be a positive number")
    if not _num(s) or s <= 0:
        errs.append(f"{where}.stop must be a positive number")
    if not isinstance(ts, list) or not ts or not all(_num(t) and t > 0 for t in ts):
        errs.append(f"{where}.targets must be a non-empty list of positive numbers")
    if errs:
        return errs
    long = d == "LONG"
    if (s >= e) if long else (s <= e):
        errs.append(f"{where}: stop {s} is on the wrong side of entry {e} for a {d}")
    for t in ts:
        if (t <= e) if long else (t >= e):
            errs.append(f"{where}: target {t} is on the wrong side of entry {e} for a {d}")
    if ts != sorted(ts, reverse=not long):
        errs.append(f"{where}: targets should be in order, nearest first")
    if price:
        lim = MAX_ENTRY_DIST.get(style, 0.05)
        if abs(e - price) / price > lim:
            errs.append(f"{where}: entry {e} is {abs(e - price) / price:.1%} from the live price {price}; limit is {lim:.0%} (typo?)")
        if abs(s - e) / e > (0.15 if style == "swing" else 0.06):
            errs.append(f"{where}: stop is {abs(s - e) / e:.1%} from the entry, which is implausibly far for a {style} trade")
    return errs


def validate_statement(d, side, rnd, price, style):
    errs = []
    want = "TAKE" if side == "bull" else "SKIP"
    if d.get("agent") != side:
        errs.append(f"agent must be '{side}'")
    if d.get("stance") != want:
        errs.append(f"stance must be '{want}' (the sides never switch)")
    if d.get("round") != rnd:
        errs.append(f"round must be {rnd}")
    if not isinstance(d.get("headline"), str) or len(d["headline"].strip()) < 10:
        errs.append("headline is missing or too short")
    ev = d.get("evidence")
    if not isinstance(ev, list) or not ev:
        errs.append("evidence must be a non-empty list")
        ev = []
    for i, e in enumerate(ev):
        for k in ("claim", "value", "source", "time"):
            if not e.get(k) and e.get(k) != 0:
                errs.append(f"evidence[{i}].{k} is missing")
    msgs = d.get("messages")
    if not isinstance(msgs, list) or not (2 <= len(msgs) <= 10):
        errs.append("messages must be a list of 2 to 10 chat messages")
        msgs = []
    for i, m in enumerate(msgs):
        if not isinstance(m, dict) or not isinstance(m.get("text"), str) or len(m["text"].strip()) < 5:
            errs.append(f"messages[{i}].text is missing")
            continue
        if len(m["text"]) > 600:
            errs.append(f"messages[{i}] is too long for a chat message ({len(m['text'])} characters; keep it under 600)")
        for j in m.get("evidence") or []:
            if not isinstance(j, int) or j < 0 or j >= len(ev):
                errs.append(f"messages[{i}] points to evidence[{j}], which does not exist")
        if rnd == 1 and m.get("reply_to"):
            errs.append(f"messages[{i}] has reply_to in Round 1 (nothing to reply to yet)")
    if side == "bull":
        errs += check_plan_numbers(d.get("plan_numbers"), price, style, "plan_numbers")
    return errs


def validate_result(d, rnd):
    errs = []
    if d.get("round") != rnd:
        errs.append(f"round must be {rnd}")
    if d.get("leader") not in ("bull", "bear", "even"):
        errs.append("leader must be bull, bear or even")
    sc = d.get("score") or {}
    for k in ("bull", "bear"):
        if not _num(sc.get(k)) or not 0 <= sc[k] <= 10:
            errs.append(f"score.{k} must be a number from 0 to 10")
    for k in ("title_plain", "summary_plain"):
        if not isinstance(d.get(k), str) or len(d[k]) < 8:
            errs.append(f"{k} is missing")
    for i, c in enumerate(d.get("checks") or []):
        if str(c.get("status", "")).lower() not in ("verified", "wrong", "stale", "unverifiable"):
            errs.append(f"checks[{i}].status must be verified, wrong, stale or unverifiable")
    return errs


def validate_verdict(d, price, style):
    errs = []
    if str(d.get("decision", "")).upper() not in ("TAKE", "SKIP"):
        errs.append("decision must be TAKE or SKIP")
    if not _num(d.get("confidence")) or not 0 <= d["confidence"] <= 100:
        errs.append("confidence must be a number from 0 to 100")
    if d.get("winner") not in ("bull", "bear", "draw"):
        errs.append("winner must be bull, bear or draw")
    for k in ("headline_plain", "explain_plain", "plan_plain", "retake_plain", "reasoning"):
        if not isinstance(d.get(k), str) or len(d[k]) < 10:
            errs.append(f"{k} is missing")
    sc = d.get("scorecard") or {}
    for side in ("bull", "bear"):
        s = sc.get(side) or {}
        parts = [s.get(k) for k in ("evidence_quality", "data_accuracy", "rebuttal_strength", "plan_reasoning")]
        if not all(_num(x) and 0 <= x <= 10 for x in parts):
            errs.append(f"scorecard.{side} needs four scores from 0 to 10")
        elif not _num(s.get("total")) or abs(sum(parts) - s["total"]) > 0.01:
            errs.append(f"scorecard.{side}.total ({s.get('total')}) is not the sum of its parts ({sum(parts)})")
    errs += check_plan_numbers(d.get("trade_plan_numbers"), price, style, "trade_plan_numbers")
    rn = d.get("retake_numbers")
    if rn is not None:
        if not isinstance(rn, dict):
            errs.append("retake_numbers must be an object or null")
        else:
            a, b = rn.get("price_above"), rn.get("price_below")
            if a is None and b is None:
                errs.append("retake_numbers needs price_above or price_below (or set the whole field to null)")
            for k, v in (("price_above", a), ("price_below", b)):
                if v is not None and (not _num(v) or v <= 0 or (price and abs(v - price) / price > 0.3)):
                    errs.append(f"retake_numbers.{k} must be a positive price near the current price")
            if rn.get("hold_minutes") is not None and (not _num(rn["hold_minutes"]) or not 5 <= rn["hold_minutes"] <= 1440):
                errs.append("retake_numbers.hold_minutes must be between 5 and 1440")
    return errs


def validate(path):
    folder = os.path.dirname(os.path.abspath(path))
    name = os.path.basename(path)
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return [f"{name} does not exist"]
    except json.JSONDecodeError as e:
        return [f"{name} is not valid JSON: {e}"]
    snap = {}
    try:
        with open(os.path.join(folder, "snapshot.json"), encoding="utf-8") as f:
            snap = json.load(f)
    except Exception:
        pass
    price, style = snap.get("price"), snap.get("style", "intraday")
    m = re.match(r"r(\d)_(bull|bear)\.json$", name)
    if m:
        return validate_statement(d, m.group(2), int(m.group(1)), price, style)
    m = re.match(r"r(\d)_result\.json$", name)
    if m:
        return validate_result(d, int(m.group(1)))
    if name == "verdict.json":
        return validate_verdict(d, price, style)
    return [f"don't know how to validate {name}"]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    bad = 0
    for p in sys.argv[1:]:
        errs = validate(p)
        folder = os.path.dirname(os.path.abspath(p))
        audit(folder, "validate", f"{os.path.basename(p)}: {'OK' if not errs else str(len(errs)) + ' problem(s): ' + '; '.join(errs)}")
        if errs:
            bad += 1
            print(f"PROBLEMS in {p}:")
            for e in errs:
                print(f"  - {e}")
        else:
            print(f"OK {p}")
    sys.exit(2 if bad else 0)


if __name__ == "__main__":
    main()
