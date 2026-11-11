# Your trade requests

Each `.json` file here is one trade you want the desk to debate. The **Add my trade** button on the
dashboard creates these files for you on GitHub, and you just tap **Commit changes**.

The next scheduled scan debates them first, then moves each file to `done/` with the debate's id
(or the reason it could not be debated). Format and rules: see `tools/trade_requests.py`.
