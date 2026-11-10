#!/usr/bin/env python3
"""Market context (I): is the whole market helping or fighting this trade?

  python tools/context.py NVDA --market us --out debates/<id>/context.json

For the asset's market it reads the main indexes and gauges (free, Yahoo + CoinGecko):
  US: S&P 500, Nasdaq, VIX, US 10-year yield, dollar index
  NSE: NIFTY 50, Bank NIFTY, India VIX, USD/INR
  crypto: Bitcoin, Bitcoin dominance, total crypto market cap change, VIX
  forex: dollar index, US 10-year yield, the pair's two currencies vs the dollar
Each index: today's change and trend (price vs its 20- and 50-day averages).
Relative strength: the asset's change today minus its main index's change (is it stronger or weaker
than the market?). The verdict: TAILWIND / NEUTRAL / HEADWIND for the proposed direction.
"""
import argparse, json, os, sys, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import market_data as md  # noqa: E402
from audit import audit  # noqa: E402

SETS = {
    "us": [("^GSPC", "S&P 500", True), ("^IXIC", "Nasdaq", False), ("^VIX", "VIX fear gauge", False), ("^TNX", "US 10-year yield", False), ("DX-Y.NYB", "Dollar index", False)],
    "nse": [("^NSEI", "NIFTY 50", True), ("^NSEBANK", "Bank NIFTY", False), ("^INDIAVIX", "India VIX fear gauge", False), ("USDINR=X", "USD/INR", False)],
    "crypto": [("BTC-USD", "Bitcoin", True), ("^VIX", "VIX fear gauge", False)],
    "forex": [("DX-Y.NYB", "Dollar index", True), ("^TNX", "US 10-year yield", False)],
}


def index_state(sym, name):
    cs, meta = md.candles_yahoo(sym, "1d", "6mo")
    closes = [c["c"] for c in cs]
    price = meta.get("regularMarketPrice") or closes[-1]
    prev = closes[-2] if len(closes) > 1 else price
    s20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
    s50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
    trend = "UP" if s20 and s50 and price > s20 > s50 else "DOWN" if s20 and s50 and price < s20 < s50 else "MIXED"
    return {"symbol": sym, "name": name, "price": round(price, 4), "change_today_pct": round((price / prev - 1) * 100, 2),
            "vs_sma20_pct": round((price / s20 - 1) * 100, 2) if s20 else None, "vs_sma50_pct": round((price / s50 - 1) * 100, 2) if s50 else None,
            "trend": trend}


def coingecko_global():
    req = urllib.request.Request("https://api.coingecko.com/api/v3/global", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read())["data"]
    return {"btc_dominance_pct": round(d["market_cap_percentage"]["btc"], 2),
            "total_mcap_change_24h_pct": round(d["market_cap_change_percentage_24h_usd"], 2)}


def compute(symbol, market="auto", direction="LONG"):
    market, sym, display = md.detect(symbol, market)
    out = {"computed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "symbol": display, "market": market,
           "direction": direction, "indexes": [], "notes": []}
    main = None
    for s, name, is_main in SETS[market]:
        try:
            st = index_state(s, name)
            out["indexes"].append(st)
            if is_main:
                main = st
        except Exception as e:
            out["notes"].append(f"{name} unavailable ({type(e).__name__})")
    if market == "crypto":
        try:
            out["crypto_market"] = coingecko_global()
        except Exception as e:
            out["notes"].append(f"CoinGecko unavailable ({type(e).__name__})")
    # the asset itself
    snap = md.build(display, market, "intraday", with_news=False)
    chg = snap.get("change_24h_pct", snap.get("change_today_pct"))
    out["asset_change_pct"] = chg
    score = 0
    reasons = []
    long = direction.upper() == "LONG"
    # in forex the main gauge is the dollar: a rising dollar pushes EUR/USD down but USD/INR up
    flip = 1
    if market == "forex":
        pair = sym.replace("=X", "")
        flip = -1 if pair[3:6] == "USD" else 1 if pair[:3] == "USD" else 0
    if main and flip:
        if main["trend"] == "UP":
            score += (1 if long else -1) * flip
            reasons.append(f"{main['name']} is in an uptrend" + (" (a rising dollar pushes this pair down)" if flip == -1 else ""))
        elif main["trend"] == "DOWN":
            score += (-1 if long else 1) * flip
            reasons.append(f"{main['name']} is in a downtrend" + (" (a falling dollar pushes this pair up)" if flip == -1 else ""))
        else:
            reasons.append(f"{main['name']} has no clear trend ({main['change_today_pct']:+.2f}% today)")
        if chg is not None and main.get("change_today_pct") is not None and market != "forex" and display.split("/")[0] != "BTC":
            rs = round(chg - main["change_today_pct"], 2)
            out["relative_strength_pct"] = rs
            if abs(rs) >= 1:
                score += (1 if rs > 0 else -1) * (1 if long else -1)
                reasons.append(f"{display} is {'stronger' if rs > 0 else 'weaker'} than {main['name']} today by {abs(rs):.1f} points")
            else:
                reasons.append(f"{display} is moving in line with {main['name']} today")
    fear = next((i for i in out["indexes"] if "VIX" in i["name"]), None)
    if fear and fear["price"] >= (20 if "India" in fear["name"] else 25):
        score += -1 if long else 0
        reasons.append(f"{fear['name']} is high ({fear['price']:.1f}): nervous market")
    if out.get("crypto_market"):
        cm = out["crypto_market"]["total_mcap_change_24h_pct"]
        if abs(cm) >= 2:
            score += (1 if cm > 0 else -1) * (1 if long else -1)
            reasons.append(f"the whole crypto market moved {cm:+.1f}% in 24h")
    out["score"] = score
    out["verdict"] = "TAILWIND" if score >= 2 else "HEADWIND" if score <= -2 else "NEUTRAL"
    out["plain"] = ({"TAILWIND": "The wider market is helping this trade: ", "HEADWIND": "The wider market is working against this trade: ",
                     "NEUTRAL": "The wider market is mixed for this trade: "}[out["verdict"]] + "; ".join(reasons) + ".") if reasons else "Not enough market context data."
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--market", default="auto")
    ap.add_argument("--direction", default="LONG")
    ap.add_argument("--out")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    res = compute(a.symbol, a.market, a.direction)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
        audit(os.path.dirname(os.path.abspath(a.out)), "context", f"{res['verdict']} (score {res['score']})")
        print(f"wrote {a.out}: {res['verdict']}: {res['plain']}")
    else:
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
