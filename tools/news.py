#!/usr/bin/env python3
"""News engine (N): fresh, timestamped, de-duplicated, trust-ranked headlines for one asset.

  python tools/news.py ETH --market crypto --style intraday --out debates/<id>/news.json

Sources (free RSS): Google News (per-asset searches, India edition for NSE), Yahoo Finance per ticker,
plus market desks: CNBC, MarketWatch (US); Economic Times Markets, Livemint, Business Standard (India);
Cointelegraph, The Block, CoinDesk (crypto); FXStreet (forex).
Rules: only items newer than the window (72 h intraday, 14 days swing), only items that mention the asset,
duplicates merged (same story from several outlets counts once, with all sources listed), each item tagged
with its age in hours and a trust tier (1 = major newsroom, 2 = specialist/aggregator, 3 = other).
"""
import argparse, json, os, re, sys, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import market_data as md  # noqa: E402
from audit import audit  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (trade-debate research script)"}
DESKS = {
    "us": ["https://www.cnbc.com/id/100003114/device/rss/rss.html", "https://feeds.content.dowjones.io/public/rss/mw_topstories"],
    "nse": ["https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "https://www.livemint.com/rss/markets",
            "https://www.business-standard.com/rss/markets-106.rss"],
    "crypto": ["https://cointelegraph.com/rss", "https://www.theblock.co/rss.xml", "https://www.coindesk.com/arc/outboundfeeds/rss/"],
    "forex": ["https://www.fxstreet.com/rss/news"],
}
TIER1 = re.compile(r"reuters|bloomberg|cnbc|wall street journal|wsj|financial times|marketwatch|economic times|livemint|mint|"
                   r"business standard|moneycontrol|coindesk|the block|associated press|ap news|barron|nikkei|hindu businessline", re.I)
TIER2 = re.compile(r"yahoo|cointelegraph|fxstreet|investing\.com|seeking alpha|benzinga|decrypt|forexlive|ndtv profit|zee business|"
                   r"business today|financial express|motley fool|tipranks|24/7 wall", re.I)
CRYPTO_NAMES = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "xrp", "BNB": "bnb", "DOGE": "dogecoin", "ADA": "cardano",
                "AVAX": "avalanche", "LINK": "chainlink", "DOT": "polkadot", "LTC": "litecoin", "ZEC": "zcash", "TON": "toncoin", "SUI": "sui"}


def get(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 307, 308) and e.headers.get("Location"):
            return get(urllib.parse.urljoin(url, e.headers["Location"]), timeout)
        raise


def parse_rss(raw, default_source):
    items = []
    for it in ET.fromstring(raw).iter("item"):
        src = it.find("source")
        t = it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date")
        try:
            dt = parsedate_to_datetime(t).astimezone(timezone.utc) if t and "," in t else datetime.fromisoformat(t.replace("Z", "+00:00"))
        except Exception:
            dt = None
        title = re.sub(r"\s+", " ", (it.findtext("title") or "")).strip()
        source = src.text if src is not None and src.text else default_source
        if " - " in title and src is not None:  # Google News appends " - Outlet"
            title = title.rsplit(" - ", 1)[0]
        items.append({"title": title, "source": source, "published_utc": dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None,
                      "_dt": dt, "url": it.findtext("link"), "summary": re.sub("<[^>]+>", "", it.findtext("description") or "")[:300]})
    return items


def keywords(market, data_symbol, display, name):
    base = display.split("/")[0].replace(".NS", "")
    kws = {base}
    if market == "crypto":
        kws.add(CRYPTO_NAMES.get(base, base).lower())
    if market == "forex":
        a, b = base[:3], base[3:6]
        kws |= {f"{a}/{b}", f"{a}{b}", {"USD": "dollar", "EUR": "euro", "GBP": "pound", "JPY": "yen", "INR": "rupee"}.get(a, a),
                {"USD": "dollar", "EUR": "euro", "GBP": "pound", "JPY": "yen", "INR": "rupee"}.get(b, b)}
    if name:
        first = re.sub(r"\b(inc|ltd|limited|corp(oration)?|plc|co)\b\.?", "", name, flags=re.I).strip().split(",")[0]
        kws.add(first)
        kws.add(first.split()[0])
    return {k for k in kws if k and len(k) >= 2}


def norm(title):
    return re.sub(r"[^a-z0-9 ]", "", title.lower())[:70]


def collect(symbol, market="auto", style="intraday", name=None):
    market, data_symbol, display = md.detect(symbol, market)
    base = display.split("/")[0].replace(".NS", "")
    q_name = name or (CRYPTO_NAMES.get(base, base) if market == "crypto" else base)
    window_h = 72 if style == "intraday" else 14 * 24
    searches = {
        "crypto": [f"{q_name} crypto", f"{base} price"],
        "us": [f"{q_name} stock", f"{base} shares"],
        "nse": [f"{q_name} share price", f"{q_name} NSE"],
        "forex": [f"{base[:3]}/{base[3:6]} forex", f"{base[:3]} {base[3:6]} exchange rate"],
    }[market]
    urls = []
    ed = "hl=en-IN&gl=IN&ceid=IN:en" if market == "nse" else "hl=en-US&gl=US&ceid=US:en"
    for q in searches:
        urls.append((f"https://news.google.com/rss/search?q={urllib.parse.quote(q + ' when:' + ('3d' if style == 'intraday' else '14d'))}&{ed}", "Google News"))
    if market in ("us", "nse", "forex"):
        urls.append((f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={urllib.parse.quote(data_symbol)}&region=US&lang=en-US", "Yahoo Finance"))
    urls += [(u, urllib.parse.urlparse(u).netloc.replace("www.", "")) for u in DESKS[market]]
    errors = []

    def fetch(pair):
        u, src = pair
        try:
            return parse_rss(get(u), src)
        except Exception as e:
            errors.append(f"{src}: {type(e).__name__}")
            return []

    with ThreadPoolExecutor(8) as ex:
        batches = list(ex.map(fetch, urls))
    now = datetime.now(timezone.utc)
    kws = keywords(market, data_symbol, display, name)
    kw_re = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(kws, key=len, reverse=True)) + r")\b", re.I)
    merged = {}
    stale = 0
    for batch, (u, _) in zip(batches, urls):
        is_search = "news.google.com" in u or "yahoo" in u
        for it in batch:
            if not it["_dt"]:
                continue
            age = (now - it["_dt"]).total_seconds() / 3600
            if age > window_h or age < -1:
                stale += 1
                continue
            if not is_search and not kw_re.search(it["title"] + " " + it["summary"]):
                continue  # market desk feeds: keep only stories about this asset
            k = norm(it["title"])
            tier = 1 if TIER1.search(it["source"] or "") else 2 if TIER2.search(it["source"] or "") else 3
            if k in merged:
                m = merged[k]
                if it["source"] not in m["sources"]:
                    m["sources"].append(it["source"])
                m["tier"] = min(m["tier"], tier)
                continue
            merged[k] = {"title": it["title"], "source": it["source"], "sources": [it["source"]], "tier": tier,
                         "published_utc": it["published_utc"], "age_hours": round(age, 1), "url": it["url"], "summary": it["summary"]}
    items = sorted(merged.values(), key=lambda x: (x["tier"], x["age_hours"]))[:25]
    items.sort(key=lambda x: x["age_hours"])
    return {"computed_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "symbol": display, "market": market, "window_hours": window_h,
            "keywords": sorted(kws), "items": items, "count": len(items), "dropped_stale": stale, "feed_errors": errors,
            "rules": f"Only items from the last {window_h} hours that mention the asset; same story from several outlets merged; "
                     "tier 1 = major newsroom, 2 = specialist or aggregator, 3 = other."}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--market", default="auto")
    ap.add_argument("--style", default="intraday", choices=["intraday", "swing"])
    ap.add_argument("--name", help="company name, improves matching (e.g. 'Reliance Industries')")
    ap.add_argument("--out")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    res = collect(a.symbol, a.market, a.style, a.name)
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2, ensure_ascii=False)
        audit(os.path.dirname(os.path.abspath(a.out)), "news", f"{res['count']} fresh items, {res['dropped_stale']} stale dropped, feed errors: {res['feed_errors']}")
        print(f"wrote {a.out}: {res['count']} fresh items ({res['dropped_stale']} stale dropped); errors: {res['feed_errors'] or 'none'}")
    else:
        print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
