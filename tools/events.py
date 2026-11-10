#!/usr/bin/env python3
"""Event guard: is a market-moving event scheduled inside the trade window?

Sources (free, no key):
  - ForexFactory weekly economic calendar (CPI, jobs, central-bank decisions...), this week + next week
  - Nasdaq earnings calendar (US stocks)
Not covered by a free feed (flagged so the agents research them on the web): NSE results dates,
RBI policy dates, crypto token unlocks.

Usage:
  python tools/events.py --market crypto --symbol BTC --style intraday --out debates/<id>/events.json
  python tools/events.py --market us --symbol AAPL --style swing
"""
import argparse, json, os, re, sys, time, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone

UA = {"User-Agent": "Mozilla/5.0 (trade-debate research script)", "Accept": "application/json, text/plain, */*"}
FF = ["https://nfs.faireconomy.media/ff_calendar_thisweek.json", "https://nfs.faireconomy.media/ff_calendar_nextweek.json"]
INTRADAY_HOURS = 8          # default length of an intraday trade window
SWING_DAYS = 10             # default length of a swing trade window
LOOKBACK_MIN = 60           # a high-impact release in the last hour still moves prices
# Tier 1: releases that routinely move every market at once. Earnings are always tier 1.
TIER1 = re.compile(r"\b(CPI|inflation rate|core inflation|PCE|non ?farm|payrolls|unemployment rate|interest rate decision|"
                   r"rate decision|FOMC|fed chair|powell|monetary policy|RBI|ECB|BoE|BoJ|press conference|"
                   r"GDP growth rate|retail sales|ISM manufacturing)\b", re.I)


CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache")


def get(url, timeout=20, cache_seconds=0):
    """GET JSON. With cache_seconds, reuse a saved copy (ForexFactory rate-limits repeat downloads)."""
    path = os.path.join(CACHE, "".join(c if c.isalnum() else "_" for c in url)[-120:] + ".json")
    if cache_seconds and os.path.exists(path) and time.time() - os.path.getmtime(path) < cache_seconds:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                data = json.loads(r.read())
            if cache_seconds:
                os.makedirs(CACHE, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f)
            return data
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (404,):
                break
            time.sleep(2 + 3 * attempt)
        except Exception as e:
            last = e
            time.sleep(1)
    if cache_seconds and os.path.exists(path):  # stale copy beats nothing; caller still sees the age
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    raise last


def currencies_for(market, symbol):
    s = symbol.upper().replace("/", "").replace("=X", "")
    if market == "forex" and len(s) >= 6:
        return {s[:3], s[3:6]}, []
    if market == "nse":
        return {"USD", "INR"}, []
    if market == "crypto":
        return {"USD"}, ["Token unlocks and exchange listings are not in the free calendar: check them on the web."]
    return {"USD"}, []


COUNTRY = {"USD": "US", "EUR": "EU", "GBP": "GB", "JPY": "JP", "INR": "IN", "AUD": "AU", "NZD": "NZ",
           "CAD": "CA", "CHF": "CH", "CNY": "CN", "SGD": "SG", "HKD": "HK"}
TV_IMPACT = {1: "High", 0: "Medium"}


def dedupe(events):
    """Drop repeats of the same event (sources and weekly files can overlap), oldest first."""
    seen, uniq = set(), []
    for e in sorted(events, key=lambda x: x["time_utc"]):
        key = (e["title"], e["currency"], e["time_utc"])
        if key not in seen:
            seen.add(key)
            uniq.append(e)
    return uniq


def tradingview_events(curr, start, end, now):
    """Primary source: TradingView's public economic calendar (covers India, so RBI decisions show up)."""
    countries = ",".join(sorted({COUNTRY[c] for c in curr if c in COUNTRY}))
    a = (start - timedelta(hours=1)).strftime("%Y-%m-%dT%H:00:00.000Z")
    b = (end + timedelta(hours=1)).strftime("%Y-%m-%dT%H:00:00.000Z")
    url = f"https://economic-calendar.tradingview.com/events?from={a}&to={b}&countries={countries}"
    req = urllib.request.Request(url, headers={**UA, "Origin": "https://in.tradingview.com", "Referer": "https://in.tradingview.com/"})
    with urllib.request.urlopen(req, timeout=20) as r:
        rows = json.loads(r.read()).get("result", [])
    out = []
    for e in rows:
        imp = TV_IMPACT.get(e.get("importance"))
        if not imp or e.get("currency") not in curr:
            continue
        t = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
        if start <= t <= end:
            out.append({"kind": "macro", "title": e.get("title"), "currency": e.get("currency"), "impact": imp,
                        "time_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "minutes_from_now": round((t - now).total_seconds() / 60),
                        "forecast": e.get("forecast"), "previous": e.get("previous"), "actual": e.get("actual")})
    return out


def macro_events(curr, start, end, now):
    try:
        return dedupe(tradingview_events(curr, start, end, now)), []
    except Exception as e:
        first_note = f"TradingView calendar unavailable ({type(e).__name__}); used ForexFactory instead."
    out, notes = [], [first_note]
    for url in FF:
        try:
            rows = get(url, cache_seconds=3600)
        except Exception as e:  # nextweek is sometimes not published yet
            if "thisweek" in url:
                notes.append(f"Economic calendar unavailable ({type(e).__name__}); treat event risk as UNKNOWN.")
            continue
        for e in rows:
            if e.get("country") not in curr or e.get("impact") not in ("High", "Medium"):
                continue
            try:
                t = datetime.fromisoformat(e["date"]).astimezone(timezone.utc)
            except Exception:
                continue
            if start <= t <= end:
                out.append({
                    "kind": "macro", "title": e.get("title"), "currency": e.get("country"), "impact": e.get("impact"),
                    "time_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "minutes_from_now": round((t - now).total_seconds() / 60),
                    "forecast": e.get("forecast") or None, "previous": e.get("previous") or None,
                })
    # de-duplicate (the two weekly files can overlap)
    seen, uniq = set(), []
    for e in sorted(out, key=lambda x: x["time_utc"]):
        k = (e["title"], e["currency"], e["time_utc"])
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq, notes


def tradingview_earnings(symbol, market, start, end, now):
    """Primary earnings source (reachable from the cloud): TradingView's screener gives the next report date
    for US and NSE stocks. Returns (events, found) where found=False means the symbol was not recognised."""
    sym = symbol.upper().split(".")[0]
    tickers = [f"NSE:{sym}"] if market == "nse" else [f"NASDAQ:{sym}", f"NYSE:{sym}", f"AMEX:{sym}"]
    body = json.dumps({"symbols": {"tickers": tickers}, "columns": ["earnings_release_next_date"]}).encode()
    req = urllib.request.Request(f"https://scanner.tradingview.com/{'india' if market == 'nse' else 'america'}/scan", data=body,
                                 headers={**UA, "Content-Type": "application/json", "Origin": "https://in.tradingview.com",
                                          "Referer": "https://in.tradingview.com/"})
    with urllib.request.urlopen(req, timeout=20) as r:
        rows = json.loads(r.read()).get("data") or []
    out = []
    for row in rows:
        ts = (row.get("d") or [None])[0]
        if not isinstance(ts, (int, float)):
            continue
        t = datetime.fromtimestamp(ts, timezone.utc)
        if start - timedelta(hours=12) <= t <= end:
            out.append({"kind": "earnings", "title": f"{sym} {'quarterly results' if market == 'nse' else 'earnings report'}",
                        "currency": "INR" if market == "nse" else "USD", "impact": "High",
                        "time_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "minutes_from_now": round((t - now).total_seconds() / 60),
                        "forecast": None, "previous": None, "source": "TradingView"})
    return out, bool(rows)


def earnings_events(symbol, start, end, now):
    sym = symbol.upper().split(".")[0]
    out, notes = [], []
    day = start.date()
    while day <= end.date():
        try:
            d = get(f"https://api.nasdaq.com/api/calendar/earnings?date={day.isoformat()}")
            for r in ((d.get("data") or {}).get("rows") or []):
                if (r.get("symbol") or "").upper() == sym:
                    when = r.get("time") or ""
                    hour = 12 if "pre" in when else 21 if "after" in when else 16  # rough UTC hour for ordering
                    t = datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)
                    out.append({"kind": "earnings", "title": f"{sym} earnings report ({when.replace('time-', '') or 'time not given'})",
                                "currency": "USD", "impact": "High", "time_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "minutes_from_now": round((t - now).total_seconds() / 60),
                                "forecast": r.get("epsForecast"), "previous": r.get("lastYearEPS")})
        except Exception as e:
            notes.append(f"Earnings calendar for {day} unavailable ({type(e).__name__}).")
        day += timedelta(days=1)
    return out, notes


def guard(market, symbol, style="intraday", hours=None, now=None):
    now = now or datetime.now(timezone.utc)
    span = timedelta(hours=hours or INTRADAY_HOURS) if style == "intraday" else timedelta(days=SWING_DAYS)
    start, end = now - timedelta(minutes=LOOKBACK_MIN), now + span
    curr, notes = currencies_for(market, symbol)
    events, n1 = macro_events(curr, start, end, now)
    notes += n1
    if market in ("us", "nse"):
        try:
            e2, found = tradingview_earnings(symbol, market, now, end, now)
            if not found:
                raise LookupError("symbol not found on TradingView")
            events += e2
        except Exception as e:
            if market == "us":  # backup source for US stocks
                e2, n2 = earnings_events(symbol, now, end, now)
                events += e2
                notes += n2
            else:
                notes.append(f"Earnings calendar for {symbol} unavailable ({type(e).__name__}): NSE results date could not be checked.")
    events.sort(key=lambda x: x["time_utc"])
    for e in events:
        e["tier"] = 1 if e["kind"] == "earnings" or TIER1.search(e["title"] or "") else 2 if e["impact"] == "High" else 3
    ahead = [e for e in events if e["minutes_from_now"] >= 0]
    t1_ahead = [e for e in ahead if e["tier"] == 1]
    earn_ahead = [e for e in ahead if e["kind"] == "earnings"]
    t1_just = [e for e in events if e["tier"] == 1 and -LOOKBACK_MIN <= e["minutes_from_now"] < 0]
    t2_ahead = [e for e in ahead if e["tier"] == 2]
    unknown = any(n.startswith("Economic calendar unavailable") for n in notes)
    earnings_unknown = market in ("us", "nse") and any(n.startswith("Earnings calendar for") for n in notes)
    blocking = earn_ahead if style == "swing" else t1_ahead
    if unknown:  # never treat "could not check" as "nothing scheduled"
        status = "BLOCK"
        plain = "The economic calendar could not be loaded from either source, so big scheduled events cannot be ruled out. Not safe to trade blind."
    elif earnings_unknown and style == "swing":
        status = "BLOCK"
        plain = "The earnings calendar could not be checked, so an earnings report inside this multi-day trade cannot be ruled out."
    elif blocking:
        e = blocking[0]
        status = "BLOCK"
        plain = (f"A major scheduled event lands inside the trade window: {e['title']} in about "
                 f"{fmt_minutes(e['minutes_from_now'])}. Prices can jump sharply either way, past any stop-loss.")
    elif t1_just:
        e = t1_just[-1]
        status = "CAUTION"
        plain = f"A major event happened {fmt_minutes(-e['minutes_from_now'])} ago ({e['title']}). Prices may still be swinging from it."
    elif earnings_unknown:
        status = "CAUTION"
        plain = "The earnings calendar could not be checked today. Reports usually come before the open or after the close, so a same-day trade is less exposed, but check the company's report date yourself."
    elif t1_ahead:  # swing trades: major macro inside a multi-day hold is a caution, not a block
        e = t1_ahead[0]
        status = "CAUTION"
        plain = f"This multi-day trade would be open during {e['title']} (in about {fmt_minutes(e['minutes_from_now'])}). Expect a big move that day."
    elif t2_ahead:
        e = t2_ahead[0]
        status = "CAUTION" if style == "intraday" and e["minutes_from_now"] <= 240 else "CLEAR"
        plain = (f"A smaller report is due: {e['title']} in about {fmt_minutes(e['minutes_from_now'])}." if status == "CAUTION"
                 else "No major scheduled events inside the trade window (only minor reports).")
    else:
        status = "CLEAR"
        plain = "No major scheduled events inside the trade window."
    return {
        "checked_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "market": market, "symbol": symbol, "style": style,
        "window_utc": [start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")],
        "currencies": sorted(curr), "status": status, "plain": plain, "events": events, "notes": notes,
        "sources": ["TradingView economic calendar (ForexFactory as backup)"] + (["TradingView earnings dates (Nasdaq as backup)"] if market == "us"
                                                                                else ["TradingView NSE results dates"] if market == "nse" else []),
    }


def fmt_minutes(m):
    m = abs(int(m))
    if m < 90:
        return f"{m} min"
    if m < 48 * 60:
        return f"{m / 60:.1f} hours"
    return f"{m / 1440:.1f} days"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, choices=["crypto", "us", "nse", "forex"])
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--style", default="intraday", choices=["intraday", "swing"])
    ap.add_argument("--hours", type=float)
    ap.add_argument("--out")
    a = ap.parse_args()
    res = guard(a.market, a.symbol, a.style, a.hours)
    text = json.dumps(res, indent=2)
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        open(a.out, "w", encoding="utf-8").write(text)
        print(f"wrote {a.out}: {res['status']}: {res['plain']}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)


if __name__ == "__main__":
    main()
