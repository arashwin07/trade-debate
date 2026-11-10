#!/usr/bin/env python3
"""Judge calibration (J): is the Judge's confidence honest, and what has it been getting wrong?

  python tools/calibration.py        # reads every outcome.json + verdict.json -> docs/calibration.json

For each resolved debate: the call (TAKE/SKIP), the Judge's confidence, and whether the call was right
(TAKE right = the trade made money; SKIP right = the trade would have lost or never filled).
Reports accuracy overall and by confidence band, plus the list of misses (missed winners and losing TAKEs)
with the Judge's own headline, so the Judge can read its own track record before ruling (Mode B).
"""
import json, os, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BANDS = [(0, 60), (60, 75), (75, 90), (90, 101)]
MIN_FOR_ADVICE = 20


def load(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def right(call, outcome):
    st, r = outcome.get("status"), outcome.get("r")
    if st in ("pending", "no_plan", None):
        return None
    if call == "TAKE":
        return None if st == "not_filled" else (r or 0) > 0
    return True if st == "not_filled" else (r or 0) <= 0


def run():
    rows = []
    base = os.path.join(ROOT, "debates")
    for d in sorted(os.listdir(base)):
        o, v = load(os.path.join(base, d, "outcome.json")), load(os.path.join(base, d, "verdict.json"))
        if not o or not v:
            continue
        call = o.get("call") or ("TAKE" if str(v.get("decision")).upper() in ("TAKE", "BUY") else "SKIP")
        ok = right(call, o)
        if ok is None:
            continue
        rows.append({"id": d, "call": call, "judge": str(v.get("decision")).upper(), "confidence": v.get("confidence"), "right": ok,
                     "status": o["status"], "r": o.get("r"), "headline": v.get("headline_plain") or v.get("summary")})
    n = len(rows)
    bands = []
    for lo, hi in BANDS:
        b = [r for r in rows if r["confidence"] is not None and lo <= r["confidence"] < hi]
        if b:
            bands.append({"confidence": f"{lo}-{min(hi, 100)}%", "n": len(b), "right": sum(r["right"] for r in b),
                          "hit_rate": round(sum(r["right"] for r in b) / len(b), 3)})
    misses = [r for r in rows if not r["right"]]
    take = [r for r in rows if r["call"] == "TAKE"]
    skip = [r for r in rows if r["call"] == "SKIP"]
    advice = []
    if n < MIN_FOR_ADVICE:
        advice.append(f"Only {n} resolved debates: too few to change any rule. Keep collecting.")
    else:
        for b in bands:
            lo = int(b["confidence"].split("-")[0])
            if b["n"] >= 8 and b["hit_rate"] < lo / 100 - 0.15:
                advice.append(f"When the Judge says {b['confidence']} sure it is right only {b['hit_rate']:.0%} of the time: lower confidence in that band.")
        if len(skip) >= 10 and sum(not r["right"] for r in skip) / len(skip) > 0.45:
            advice.append("Many skipped trades would have won: the TAKE rules may be too strict for current markets.")
        if len(take) >= 10 and sum(r["right"] for r in take) / len(take) < 0.4:
            advice.append("Many TAKE calls lost: tighten the TAKE rules.")
    out = {"computed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "resolved": n,
           "accuracy": round(sum(r["right"] for r in rows) / n, 3) if n else None,
           "take": {"n": len(take), "right": sum(r["right"] for r in take)}, "skip": {"n": len(skip), "right": sum(r["right"] for r in skip)},
           "by_confidence": bands, "misses": misses[-10:], "advice": advice,
           "plain": (f"The Judge has been right in {sum(r['right'] for r in rows)} of {n} resolved debates." if n else "No resolved debates yet.")}
    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    with open(os.path.join(ROOT, "docs", "calibration.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    o = run()
    print(o["plain"], "| advice:", o["advice"])
    for m in o["misses"]:
        print(f"  MISS {m['id']}: {m['call']} at {m['confidence']}% -> {m['status']} {m['r']:+}R | {m['headline'][:100]}")
