#!/usr/bin/env python3
"""Agent quality scores (Q): how accurate is each agent over time?

  python tools/quality.py      # -> docs/quality.json

Per agent (Bull Claude, Bear Claude), across every debate:
  - claim checker: numbers confirmed / wrong / unconfirmed (claims_r*.json)
  - Judge's fact checks: verified / wrong / stale / unverifiable (r*_result.json and verdict.json)
  - guardrail failures recorded in audit.log (files that had to be re-written)
For the Judge: accuracy of its calls from docs/calibration.json.
Use it to see whether a change to an agent's instructions made it better or worse.
"""
import glob, json, os, re, sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def run():
    agents = {s: {"debates": 0, "numbers_checked": 0, "numbers_confirmed": 0, "numbers_wrong": 0, "numbers_unconfirmed": 0,
                  "judge_verified": 0, "judge_wrong": 0, "judge_stale": 0, "judge_unverifiable": 0, "guardrail_failures": 0}
              for s in ("bull", "bear")}
    base = os.path.join(ROOT, "debates")
    for d in sorted(os.listdir(base)):
        f = os.path.join(base, d)
        if not os.path.isdir(f):
            continue
        seen = False
        for p in glob.glob(os.path.join(f, "claims_r*.json")):
            c = load(p) or {}
            for s in ("bull", "bear"):
                x = c.get(s) or {}
                a = agents[s]
                a["numbers_checked"] += x.get("checked", 0)
                a["numbers_confirmed"] += x.get("matched", 0)
                a["numbers_wrong"] += x.get("wrong", 0)
                a["numbers_unconfirmed"] += x.get("unconfirmed", 0)
                seen = True
        checks = []
        for p in glob.glob(os.path.join(f, "r*_result.json")):
            checks += (load(p) or {}).get("checks") or []
        checks += (load(os.path.join(f, "verdict.json")) or {}).get("claim_checks") or []
        for c in checks:
            s, st = c.get("by"), str(c.get("status", "")).lower()
            if s in agents and st in ("verified", "wrong", "stale", "unverifiable"):
                agents[s]["judge_" + st] += 1
                seen = True
        try:
            log = open(os.path.join(f, "audit.log"), encoding="utf-8").read()
            for s in ("bull", "bear"):
                agents[s]["guardrail_failures"] += len(re.findall(rf"r\d_{s}\.json: \d+ problem", log))
        except Exception:
            pass
        if seen:
            for s in agents:
                agents[s]["debates"] += 1
    for s, a in agents.items():
        judged = a["judge_verified"] + a["judge_wrong"] + a["judge_stale"]
        a["accuracy_pct"] = round(100 * a["judge_verified"] / judged, 1) if judged else None
        a["code_confirmed_pct"] = round(100 * a["numbers_confirmed"] / a["numbers_checked"], 1) if a["numbers_checked"] else None
    cal = load(os.path.join(ROOT, "docs", "calibration.json")) or {}
    out = {"computed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "agents": agents,
           "judge": {"resolved": cal.get("resolved"), "accuracy": cal.get("accuracy")},
           "plain": "; ".join(f"{'Bull' if s == 'bull' else 'Bear'} Claude: {a['accuracy_pct']}% of checked claims correct, "
                              f"{a['numbers_wrong']} wrong numbers caught by code" for s, a in agents.items() if a["accuracy_pct"] is not None)}
    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    with open(os.path.join(ROOT, "docs", "quality.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    o = run()
    print(o["plain"] or "No data yet.")
    for s, a in o["agents"].items():
        print(s, {k: a[k] for k in ("debates", "accuracy_pct", "code_confirmed_pct", "numbers_wrong", "judge_wrong", "judge_unverifiable", "guardrail_failures")})
