---
name: trade-settings
description: Show or change the trading desk's settings in plain words: capital per market, risk per trade, daily limits, minimum reward-to-risk, shorting rules, broker costs, AI usage limits. Use when the user says /trade-settings, "set my capital", "change my risk", "my account size is…", "allow shorting", "show my settings".
argument-hint: "[show | what to change]"
---

# Settings

From the project root:
- **Show:** `python tools/settings.py show` and read the lines back in plain words.
- **Change:** turn the user's words into setting paths and run `python tools/settings.py set <path> <value>` once per value, e.g.
  - "my NSE capital is 2 lakh" → `accounts.nse.capital 200000`
  - "risk half a percent per trade" → `risk.risk_per_trade_pct 0.5`
  - "never lose more than 1000 rupees on a trade" → `risk.max_loss_per_trade 1000` (applies to every market's account currency: say so)
  - "allow intraday shorts on NSE" → `risk.allow_short.nse_intraday true`
  - "unset my crypto capital" → `accounts.crypto.capital null`
  If a value is ambiguous (which market? which currency?), ask before saving. The tool refuses values outside safe bounds; tell the user why.
- Broker cost rates live under `costs` in `config/desk.json`; change them only with numbers the user gives from their broker's charges page.
- After any change: `python tools/settings.py check`, `python tools/render.py --all`, and in the cloud or if the user wants it synced: `git add config docs && git commit -qm "Settings: <what changed>" && git push origin HEAD:main` (the scheduled cloud runs read the settings from GitHub).
- Confirm what changed, old → new, in one line each.
