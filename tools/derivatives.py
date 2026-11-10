#!/usr/bin/env python3
"""Derivatives positioning (D): where is the leveraged money leaning?

  python tools/derivatives.py ETH --market crypto --out debates/<id>/derivatives.json

Crypto (Binance USD-M futures, free): open interest now and its 24h change (are new bets being opened?),
funding rate now and its recent average (who pays to hold: longs or shorts?), the share of accounts that
are long vs short (crowd positioning), and top traders' long/short ratio.
Reading it: rising open interest + rising price = new buyers; rising open interest + falling price = new
sellers; very one-sided crowds and high funding are fuel for a sharp move the other way (a "squeeze").
US and NSE options data (open interest, put/call ratio) has no reliable free feed; this says so plainly.
"""
import argparse, json, os, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import market_data as md  # noqa: E402
from audit import audit  # noqa: E402

FAPI = "https://fapi.binance.com"


def crypto(sym):
    g = lambda p: md.get(FAPI + p)
    oi_now = float(g(f"/fapi/v1/openInterest?symbol={sym}")["openInterest"])
    hist = g(f"/futures/data/openInterestHist?symbol={sym}&period=1h&limit=25")
    oi_24h = float(hist[0]["sumOpenInterest"]) if hist else None
    fund = g(f"/fapi/v1/fundingRate?symbol={sym}&limit=21")
    rates = [float(x["fundingRate"]) * 100 for x in fund]
    ls = g(f"/futures/data/globalLongShortAccountRatio?symbol={sym}&period=1h&limit=1")
    top = g(f"/futures/data/topLongShortPositionRatio?symbol={sym}&period=1h&limit=1")
    f = {
        "open_interest": oi_now, "open_interest_change_24h_pct": round((oi_now / oi_24h - 1) * 100, 2) if oi_24h else None,
        "funding_now_pct": round(rates[-1], 4) if rates else None, "funding_avg_7d_pct": round(sum(rates) / len(rates), 4) if rates else None,
        "accounts_long_pct": round(float(ls[0]["longAccount"]) * 100, 1) if ls else None,
        "top_traders_long_short_ratio": round(float(top[0]["longShortRatio"]), 2) if top else None,
    }
    notes = []
    if f["open_interest_change_24h_pct"] is not None:
        notes.append(f"open bets {'rose' if f['open_interest_change_24h_pct'] > 0 else 'fell'} {abs(f['open_interest_change_24h_pct'])}% in 24h")
    if f["funding_now_pct"] is not None:
        notes.append(f"funding {f['funding_now_pct']:+.4f}% ({'futures above spot: long holders pay' if f['funding_now_pct'] > 0 else 'futures below spot: short holders pay'})")
    if f["accounts_long_pct"] is not None:
        notes.append(f"{f['accounts_long_pct']}% of accounts are long")
        if f["accounts_long_pct"] >= 70 or f["accounts_long_pct"] <= 30:
            notes.append("the crowd is very one-sided: risk of a squeeze the other way")
    return f, notes


def compute(symbol, market="auto"):
    market, sym, display = md.detect(symbol, market)
    out = {"computed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "symbol": display, "market": market}
    if market != "crypto":
        out.update({"facts": None, "plain": {"us": "US options positioning (open interest, put/call ratio) has no reliable free data feed, so it is not included.",
                                             "nse": "NSE option-chain data (open interest, put/call ratio) blocks automated free access, so it is not included.",
                                             "forex": "Spot forex has no central positioning data; it is not included."}[market]})
        return out
    try:
        f, notes = crypto(sym)
        out.update({"facts": f, "source": "Binance USD-M futures", "plain": display + ": " + "; ".join(notes) + "."})
    except Exception as e:
        out.update({"facts": None, "error": f"{type(e).__name__}: {e}", "plain": "Futures data unavailable (Binance futures may be blocked from this network)."})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--market", default="auto")
    ap.add_argument("--out")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    res = compute(a.symbol, a.market)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
        audit(os.path.dirname(os.path.abspath(a.out)), "derivs", res["plain"][:150])
        print(f"wrote {a.out}: {res['plain']}")
    else:
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
