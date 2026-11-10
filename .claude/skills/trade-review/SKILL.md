---
name: trade-review
description: The weekly lessons review. Updates the journal, the Judge's calibration, agent quality scores, the practice account and a code backtest of the desk's rules on the watchlist, then writes plain-language lessons (what worked, what failed, what to change) to docs/lessons.json for the dashboard. Use when the user says /trade-review, "weekly review", "what did we learn", "how is the desk doing".
---

# Weekly lessons review

From the project root:
1. `python tools/outcomes.py`, `python tools/calibration.py`, `python tools/quality.py`, `python tools/paper.py`.
2. For each active watchlist entry (and, if the watchlist is empty, the three most-debated assets in `debates/`): `python tools/backtest.py <symbol> --market <m> --direction <d>`.
3. Read `docs/calibration.json`, `docs/quality.json`, `docs/paper.json`, the backtests and the `audit.log` of this week's debates.
4. Write `docs/lessons.json`:
   `{"week_of": "<date>", "headline": "<one sentence>", "worked": ["..."], "failed": ["..."], "changes_suggested": [{"what": "...", "why": "...", "evidence": "..."}], "numbers": {"debates": n, "take": n, "skip": n, "judge_accuracy": x, "paper_return_pct": x}}`
   Plain language for a beginner. Base every point on the files above; with fewer than 20 resolved debates, say the sample is too small to change rules and suggest only data-quality fixes.
5. `python tools/render.py --all`; in the cloud commit and push `docs`.
6. Tell the user the headline, the top 3 lessons and any suggested change. **Never change `config/desk.json` or an agent's instructions yourself here**: suggest; the user decides (then `/trade-settings`).
