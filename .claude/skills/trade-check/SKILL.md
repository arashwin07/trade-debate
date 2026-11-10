---
name: trade-check
description: Quick code-only check of any trade plan in any market (crypto, US, NSE, forex), no debate. Gives the event guard, plan math (reward-to-risk, stop size in ATR, entry distance), Time Machine odds (10,000 replays + real history), costs, position size from your settings and the PASS/BLOCK risk gate with plain reasons. Use when the user says /trade-check, "check my plan", "what are the odds", "size this trade", "is this stop too tight", or gives entry/stop/target numbers.
argument-hint: SYMBOL long|short entry X stop Y target Z [target Z2] [intraday|swing] [market]
---

# Trade check (no debate, all code)

Parse `$ARGUMENTS` into symbol, direction, entry, stop, one or more targets, style (default intraday) and market (auto-detect if missing). If entry, stop or target is missing, ask for it: never guess a level.

Run from the project root:
```
python tools/desk.py check --market <market> --symbol <SYMBOL> --style <style> --direction <LONG|SHORT> --entry <X> --stop <Y> --target <Z> [--target <Z2>]
```

Reply in plain words, in this order:
1. **Gate: PASS or BLOCK**, then each BLOCK and WARN reason exactly as printed.
2. The plan math: risk per unit, reward-to-risk per target (before and after costs), stop size in ATR, how far the entry is from the live price.
3. The Time Machine: target-first %, stop-first %, neither %, the real-history line and the verdict line exactly as printed; say it is a simulation from the last 60 days, not a prediction.
4. Position size and money at risk, or "capital not set in config/desk.json".
Explain any trading word the first time you use it. Never place an order.
