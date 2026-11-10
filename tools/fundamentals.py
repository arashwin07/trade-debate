#!/usr/bin/env python3
"""Fundamentals fact sheet (F): the business (or coin) behind the price, in numbers.

  python tools/fundamentals.py NVDA --market us --out debates/<id>/fundamentals.json
  python tools/fundamentals.py RELIANCE --market nse
  python tools/fundamentals.py ETH --market crypto

Stocks (US and NSE), from Yahoo's free fundamentals series: revenue, net income, diluted EPS, operating
and free cash flow, total debt, cash, equity (annual, last 4 years + latest quarters), valuation
(trailing P/E, forward P/E, price/book, market cap) and derived ratios: revenue and EPS growth,
net margin, debt-to-equity. Crypto, from CoinGecko: market cap and rank, circulating vs max supply,
distance from all-time high, 24h volume / market cap.
Forex has no company fundamentals; the pair's drivers are in context.json and events.json.
"""
import argparse, json, os, sys, urllib.parse, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import market_data as md  # noqa: E402
from audit import audit  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0"}
ANNUAL = ["TotalRevenue", "NetIncome", "DilutedEPS", "OperatingCashFlow", "FreeCashFlow", "TotalDebt", "CashAndCashEquivalents", "StockholdersEquity"]
VALUATION = ["trailingPeRatio", "forwardPeRatio", "trailingPbRatio", "trailingMarketCap", "trailingPegRatio"]
COINGECKO_ID = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple", "BNB": "binancecoin", "DOGE": "dogecoin",
                "ADA": "cardano", "AVAX": "avalanche-2", "LINK": "chainlink", "DOT": "polkadot", "LTC": "litecoin", "ZEC": "zcash",
                "TON": "the-open-network", "SUI": "sui", "TRX": "tron", "SHIB": "shiba-inu", "PEPE": "pepe", "NEAR": "near", "UNI": "uniswap"}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return json.loads(r.read())


def series(sym, types):
    q = ",".join(types)
    d = get(f"https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{urllib.parse.quote(sym)}"
            f"?type={q}&period1=1500000000&period2={int(datetime.now().timestamp()) + 86400}")
    out = {}
    for r in d.get("timeseries", {}).get("result", []):
        t = r["meta"]["type"][0]
        pts = [p for p in (r.get(t) or []) if p]
        out[t] = [{"date": p["asOfDate"], "value": p["reportedValue"]["raw"], "currency": p.get("currencyCode")} for p in pts]
    return out


def last(s, k, n=1):
    v = s.get(k) or []
    return v[-n]["value"] if len(v) >= n else None


def growth(s, k):
    a, b = last(s, k, 1), last(s, k, 2)
    return round((a / b - 1) * 100, 1) if a is not None and b not in (None, 0) and b > 0 else None


def stock(sym, market):
    ann = series(sym, ["annual" + t for t in ANNUAL])
    qtr = series(sym, ["quarterly" + t for t in ("TotalRevenue", "NetIncome", "DilutedEPS")])
    val = series(sym, VALUATION)
    A = {k.replace("annual", ""): v for k, v in ann.items()}
    Q = {k.replace("quarterly", ""): v for k, v in qtr.items()}
    V = {k: (v[-1]["value"] if v else None) for k, v in val.items()}
    cur = next((v[-1]["currency"] for v in A.values() if v and v[-1].get("currency")), None)
    rev, ni, eq, debt = last(A, "TotalRevenue"), last(A, "NetIncome"), last(A, "StockholdersEquity"), last(A, "TotalDebt")
    facts = {
        "currency": cur,
        "fiscal_year_end": (A.get("TotalRevenue") or [{}])[-1].get("date"),
        "revenue": rev, "revenue_growth_pct": growth(A, "TotalRevenue"),
        "net_income": ni, "net_margin_pct": round(ni / rev * 100, 1) if rev and ni is not None else None,
        "eps_diluted": last(A, "DilutedEPS"), "eps_growth_pct": growth(A, "DilutedEPS"),
        "operating_cash_flow": last(A, "OperatingCashFlow"), "free_cash_flow": last(A, "FreeCashFlow"),
        "total_debt": debt, "cash": last(A, "CashAndCashEquivalents"), "equity": eq,
        "debt_to_equity": round(debt / eq, 2) if debt is not None and eq and eq > 0 else None,
        "latest_quarter": {"date": (Q.get("TotalRevenue") or [{}])[-1].get("date"), "revenue": last(Q, "TotalRevenue"),
                           "revenue_vs_prior_quarter_pct": growth(Q, "TotalRevenue"), "net_income": last(Q, "NetIncome"), "eps": last(Q, "DilutedEPS")},
        "valuation": {"pe_trailing": V.get("trailingPeRatio"), "pe_forward": V.get("forwardPeRatio"), "price_to_book": V.get("trailingPbRatio"),
                      "market_cap": V.get("trailingMarketCap"), "peg": V.get("trailingPegRatio")},
    }
    flags = []
    if facts["revenue_growth_pct"] is not None:
        flags.append(f"Revenue {'grew' if facts['revenue_growth_pct'] >= 0 else 'fell'} {abs(facts['revenue_growth_pct'])}% last year")
    if facts["net_margin_pct"] is not None:
        flags.append(f"keeps {facts['net_margin_pct']}% of sales as profit")
    if facts["debt_to_equity"] is not None:
        flags.append(f"debt is {facts['debt_to_equity']}x its equity" + (" (high)" if facts["debt_to_equity"] > 2 else ""))
    if facts["free_cash_flow"] is not None and facts["free_cash_flow"] < 0:
        flags.append("burning cash (negative free cash flow)")
    pe = facts["valuation"]["pe_trailing"]
    if pe:
        flags.append(f"priced at {pe:.0f}x its yearly profit (P/E)")
    return facts, flags


def crypto(base):
    cid = COINGECKO_ID.get(base, base.lower())
    d = get(f"https://api.coingecko.com/api/v3/coins/{cid}?localization=false&tickers=false&community_data=false&developer_data=false")
    m = d["market_data"]
    price, ath = m["current_price"]["usd"], m["ath"]["usd"]
    circ, mx = m.get("circulating_supply"), m.get("max_supply")
    facts = {"name": d.get("name"), "market_cap_usd": m["market_cap"]["usd"], "rank": d.get("market_cap_rank"),
             "circulating_supply": circ, "max_supply": mx, "supply_issued_pct": round(circ / mx * 100, 1) if circ and mx else None,
             "ath_usd": ath, "below_ath_pct": round((1 - price / ath) * 100, 1) if ath else None,
             "volume_to_mcap_pct": round(m["total_volume"]["usd"] / m["market_cap"]["usd"] * 100, 2) if m["market_cap"]["usd"] else None,
             "change_7d_pct": m.get("price_change_percentage_7d"), "change_30d_pct": m.get("price_change_percentage_30d"),
             "change_1y_pct": m.get("price_change_percentage_1y")}
    flags = [f"#{facts['rank']} by market value", f"{facts['below_ath_pct']}% below its all-time high",
             f"{facts['change_30d_pct']:+.1f}% over 30 days" if facts["change_30d_pct"] is not None else ""]
    if facts["supply_issued_pct"] is not None and facts["supply_issued_pct"] < 70:
        flags.append(f"only {facts['supply_issued_pct']}% of the max supply exists so far (more coins will come)")
    return facts, [f for f in flags if f]


def compute(symbol, market="auto"):
    market, sym, display = md.detect(symbol, market)
    out = {"computed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "symbol": display, "market": market}
    if market == "forex":
        out.update({"facts": None, "plain": "Currencies have no company accounts; their drivers are interest rates, inflation and central banks (see the event guard and market context)."})
        return out
    facts, flags = crypto(display.split("/")[0]) if market == "crypto" else stock(sym, market)
    out.update({"facts": facts, "source": "CoinGecko" if market == "crypto" else "Yahoo Finance fundamentals",
                "plain": (display + ": " + "; ".join(flags) + ".") if flags else "No fundamentals available."})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--market", default="auto")
    ap.add_argument("--out")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        res = compute(a.symbol, a.market)
    except Exception as e:
        res = {"symbol": a.symbol, "error": f"{type(e).__name__}: {e}", "plain": "Fundamentals could not be loaded."}
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
        audit(os.path.dirname(os.path.abspath(a.out)), "fundament", res.get("plain", "")[:150])
        print(f"wrote {a.out}: {res.get('plain')}")
    else:
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
