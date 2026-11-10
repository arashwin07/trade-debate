#!/usr/bin/env python3
"""Usage budget (U): keeps the 24/7 runs inside your Claude plan.

  python tools/budget.py check      # prints how many full debates are left today; exit 1 if none
  python tools/budget.py status     # same, plus today's debates

A full debate costs about 10 AI agent calls (2 debaters x 3 rounds, 3 round results, 1 final Judge).
The day is counted in your own timezone (config owner.utc_offset_minutes).
"""
import json, os, sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALLS_PER_DEBATE = 10


def cfg():
    with open(os.path.join(ROOT, "config", "desk.json"), encoding="utf-8") as f:
        return json.load(f)


def today_debates(c):
    off = c["owner"].get("utc_offset_minutes", 0) * 60
    today = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + off, timezone.utc).date()
    out = []
    base = os.path.join(ROOT, "debates")
    for d in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        try:
            with open(os.path.join(base, d, "meta.json"), encoding="utf-8") as f:
                m = json.load(f)
            t = datetime.fromisoformat(m["created_utc"].replace("Z", "+00:00"))
        except Exception:
            continue
        if datetime.fromtimestamp(t.timestamp() + off, timezone.utc).date() == today:
            out.append(d)
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    c = cfg()
    b = c["budget"]
    done = today_debates(c)
    left = max(0, b["max_debates_per_day"] - len(done))
    print(f"Debates today: {len(done)} of {b['max_debates_per_day']} (about {len(done) * CALLS_PER_DEBATE} agent calls). Left today: {left}. "
          f"Per scan: at most {b['max_debates_per_scan']}.")
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        for d in done:
            print("  ", d)
    sys.exit(0 if left > 0 else 1)


if __name__ == "__main__":
    main()
