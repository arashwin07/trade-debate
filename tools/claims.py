#!/usr/bin/env python3
"""Claim checker (C): code compares every data number an agent cites with the data actually recorded.

  python tools/claims.py debates/<id> --round N     -> debates/<id>/claims_rN.json (+ printed summary)

What counts as recorded data: snapshot.json, every fresh_*.json pull the agents saved, events.json,
levels.json, optimizer.json and the desk files. Two kinds of check:
  1. Named indicator + timeframe ("1h ATR 3.86", "15m RSI 28.5"): the number must match THAT indicator on
     THAT timeframe in some recorded pull. Matching a different timeframe is flagged as "wrong timeframe".
  2. Any other number cited from a data source: it must appear somewhere in the recorded data (with rounding).
Evidence cited from web articles is left to the Judge (it needs reading, not arithmetic).
"""
import argparse, glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from audit import audit  # noqa: E402

DATA_SOURCE = re.compile(r"snapshot|desk|binance|yahoo|market_data|fresh|time ?machine|live|levels|optimizer|events\.json|order ?book|replay|\.json", re.I)
DATE_TIME = re.compile(r"\d{4}-\d{2}-\d{2}(T[\d:]+Z?)?|\b\d{1,2}:\d{2}(:\d{2})?\b|\b\d{1,2}(:\d{2})?\s?(UTC|IST|ET|GMT|Z)\b", re.I)
NUM = re.compile(r"[-+]?\$?\d[\d,]*\.?\d*")
TF = [("5m", r"\b5\s?-?m(in(ute)?s?)?\b"), ("15m", r"\b15\s?-?m(in(ute)?s?)?\b"), ("1h", r"\b(1\s?-?h(our)?|hourly|60\s?-?m(in)?)\b"),
      ("4h", r"\b4\s?-?h(our)?\b"), ("1d", r"\b(1\s?-?d(ay)?|daily)\b"), ("1wk", r"\b(weekly|1\s?-?w(ee)?k)\b")]
METRIC = [("rsi14", r"\bRSI\b"), ("atr14", r"\bATR\b"), ("ema9", r"\bEMA\s?-?9\b"), ("ema21", r"\bEMA\s?-?21\b"),
          ("sma20", r"\bSMA\s?-?20\b"), ("sma50", r"\bSMA\s?-?50\b"), ("sma200", r"\bSMA\s?-?200\b"),
          ("session_vwap_utc_day", r"\bVWAP\b")]


def load(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def leaves(o, out):
    if isinstance(o, bool):
        return
    if isinstance(o, (int, float)):
        out.append(float(o))
    elif isinstance(o, dict):
        for v in o.values():
            leaves(v, out)
    elif isinstance(o, list):
        for v in o:
            leaves(v, out)
    return out


def numbers(text):
    """[(value, decimals, position, suffix)] where suffix is '%', 'x' (a ratio / R multiple) or ''."""
    text = DATE_TIME.sub(lambda m: " " * len(m.group()), str(text))
    out = []
    for m in NUM.finditer(text):
        raw = m.group().replace("$", "").replace(",", "").rstrip(".")
        try:
            v = float(raw)
        except ValueError:
            continue
        dec = len(raw.split(".")[1]) if "." in raw else 0
        nxt = text[m.end():m.end() + 2].strip()[:1].lower()
        suffix = "%" if nxt == "%" else "x" if nxt in ("x", "r", "×") else ""
        out.append((abs(v), dec, m.start(), suffix))
    return out


def close(a, dec, b, pct=False):
    """a (as typed, with dec decimals) matches recorded b, allowing rounding; a typed % may match a fraction."""
    cands = (b, b * 100) if pct else (b,)
    for cand in cands:
        if abs(a - abs(cand)) <= max(0.006 * abs(cand), 0.6 * 10 ** (-dec)):
            return True
    return False


def tf_values(pulls):
    """{(metric, tf): [values across all pulls]}"""
    vals = {}
    for p in pulls:
        for t in p.get("timeframes", []) or []:
            tf = t.get("timeframe")
            for metric, _ in METRIC:
                v = t.get(metric)
                if isinstance(v, (int, float)):
                    vals.setdefault((metric, tf), []).append(float(v))
    return vals


FILE_RX = re.compile(r"[\w.\-]+\.json", re.I)
ALIASES = [(r"\bsnapshot\b", "snapshot.json"), (r"\boptimi[sz]er\b", "optimizer.json"), (r"\blevels\b", "levels.json"),
           (r"\bevents?\b", "events.json"), (r"\bregime\b", "regime.json"), (r"\bcontext\b", "context.json")]
# counts and odds stated in words: "13 target vs 33 stop of 59", "35.8% target first", "62.5% stop first"
BINDINGS = [
    (re.compile(r"(\d+)\s*targets?\b(?!\s*first)", re.I), "target", False),
    (re.compile(r"(\d+)\s*stops?\b(?!\s*first)", re.I), "stop", False),
    (re.compile(r"(\d+)\s*neither\b", re.I), "neither", False),
    (re.compile(r"\bof\s+(\d+)\b(?!\s*(?:plans?|candidates?|replays?|ideas?|trades?|levels?))", re.I), "samples", False),
    (re.compile(r"(\d+(?:\.\d+)?)\s*%\s*target[- ]first", re.I), "p_target", True),
    (re.compile(r"(\d+(?:\.\d+)?)\s*%\s*stop[- ]first", re.I), "p_stop", True),
]


def keyed(o, key, out):
    """All numeric values stored under `key` anywhere inside o."""
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key and isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append(float(v))
            keyed(v, key, out)
    elif isinstance(o, list):
        for v in o:
            keyed(v, key, out)
    return out


def cited(source, files):
    """The recorded files an evidence item names as its source."""
    names = {n for n in FILE_RX.findall(source or "") if n in files}
    for rx, n in ALIASES:
        if re.search(rx, source or "", re.I) and n in files:
            names.add(n)
    if re.search(r"\bdesk\b", source or "", re.I) and not any(n.startswith("desk_") for n in names):
        names |= {n for n in files if n.startswith("desk_")}
    return sorted(names)


def check_bindings(text, cited_names, files):
    """Counts/odds written in words, checked against the SAME key in the cited file (or any file if none cited)."""
    found = []
    for rx, key, is_pct in BINDINGS:
        if key == "samples" and not re.search(r"histor|past|real|starts?|days?|samples?", text, re.I):
            continue  # "of 24" only means history samples when the text is about history
        for m in rx.finditer(text):
            a = float(m.group(1))
            dec = len(m.group(1).split(".")[1]) if "." in m.group(1) else 0
            where = cited_names or sorted(files)
            vals = {n: keyed(files[n], key, []) for n in where}
            vals = {n: v for n, v in vals.items() if v}
            if not vals:
                continue
            ok_in = [n for n, vs in vals.items() if any(close(a, dec, b, pct=is_pct) for b in vs)]
            if ok_in:
                found.append((a, key, "confirmed", ok_in, None))
                continue
            elsewhere = [n for n in files if n not in vals and any(close(a, dec, b, pct=is_pct) for b in keyed(files[n], key, []))]
            expected = next(iter(vals.values()))[-1]
            found.append((a, key, "stale" if elsewhere else "wrong", elsewhere, expected * (100 if is_pct else 1)))
    return found


def check_statement(stmt, pool, tfv, has_fresh=True, files=None):
    files = files or {}
    res = {"checked": 0, "matched": 0, "issues": []}
    for i, ev in enumerate(stmt.get("evidence") or []):
        src = f"{ev.get('source', '')}"
        if not DATA_SOURCE.search(src) or re.search(r"snippet|article|news|reuters|cnbc|coindesk|http", src, re.I):
            continue
        handled = set()
        # 1. indicator + timeframe: only when the claim names exactly one timeframe, and only the number right after the name
        for part in (str(ev.get("claim", "")), str(ev.get("value", ""))):
            tfs = {name for name, rx in TF if re.search(rx, part, re.I)} or {name for name, rx in TF if re.search(rx, str(ev.get("claim", "")), re.I)}
            if len(tfs) != 1:
                continue
            tf = tfs.pop()
            nums_here = numbers(part)
            for metric, rx in METRIC:
                for mm in re.finditer(rx, part, re.I):
                    after = [n for n in nums_here if 0 <= n[2] - mm.end() <= 25 and n[3] == ""
                             and not re.match(r"\s?-?\d", part[mm.end():mm.end() + 3]) or False]
                    after = [n for n in nums_here if 0 <= n[2] - mm.end() <= 25 and n[3] == ""]
                    if not after:
                        continue
                    a, dec = after[0][0], after[0][1]
                    if metric in ("ema9", "ema21", "sma20", "sma50", "sma200") and after[0][2] - mm.end() <= 1:
                        continue  # the "9" in "EMA9" itself
                    want = tfv.get((metric, tf), [])
                    if not want or (metric, a) in handled:
                        continue
                    handled.add((metric, a))
                    res["checked"] += 1
                    if any(close(a, dec, b) for b in want):
                        res["matched"] += 1
                        continue
                    other = sorted({k[1] for k, vs in tfv.items() if k[0] == metric and k[1] != tf and any(close(a, dec, b) for b in vs)})
                    if other:
                        res["issues"].append({"evidence": i, "claim": ev.get("claim"), "number": a, "problem": "wrong_timeframe", "level": "wrong",
                                              "plain": f"{a:g} is the {metric.replace('14', '').replace('session_vwap_utc_day', 'vwap').upper()} on the {other[0]} chart, not the {tf} chart (recorded {tf} value: {want[-1]:g}).",
                                              "expected": want[-1]})
                    else:
                        res["issues"].append({"evidence": i, "claim": ev.get("claim"), "number": a, "problem": "mismatch", "level": "wrong",
                                              "plain": f"{a:g} does not match the recorded {tf} {metric.replace('14', '').upper()} ({', '.join(f'{x:g}' for x in want[-3:])}).",
                                              "expected": want[-1]})
        # 2. counts and odds written in words, in the claim text AND the value, checked against the cited file's same key
        names = cited(src, files)
        explicit = bool([n for n in FILE_RX.findall(src) if n in files])  # "wrong" needs an exact file name, not a loose mention
        self_reported = bool(re.search(r"not saved|unsaved|own .*run|my own|unconfirmed", src, re.I))
        done = {a for (_, a) in handled}
        for a, key, status, where, expected in check_bindings(f"{ev.get('claim', '')} | {ev.get('value', '')}", names, files):
            if a in done:
                continue
            done.add(a)
            res["checked"] += 1
            if status == "confirmed":
                res["matched"] += 1
            elif status == "stale":
                res["issues"].append({"evidence": i, "claim": ev.get("claim"), "number": a, "problem": "stale", "level": "unconfirmed",
                                      "plain": f"{a:g} ({key}) is from an older run ({', '.join(where)}); the file cited now says {expected:g}. Out of date, not invented."})
            elif self_reported or not explicit:
                res["issues"].append({"evidence": i, "claim": ev.get("claim"), "number": a, "problem": "unconfirmed_count", "level": "unconfirmed",
                                      "plain": f"{a:g} ({key}) could not be confirmed: the agent did not cite a saved file for it" +
                                               (" (it says these are its own unsaved runs)." if self_reported else ".")})
            else:
                res["issues"].append({"evidence": i, "claim": ev.get("claim"), "number": a, "problem": "mismatch_cited_file", "level": "wrong",
                                      "plain": f"{a:g} ({key}) does not match {', '.join(names) or 'the recorded data'}, which says {expected:g}.",
                                      "expected": expected})
        # 3. other numbers in the value: confirm them in the cited file first, then anywhere in the recorded data
        cited_pool = leaves([files[n] for n in names], []) if names else None
        for a, dec, _, suffix in numbers(ev.get("value", "")):
            if a in done or a == 0 or (dec == 0 and a < 10):  # small counts like "3 of 5" are not data
                continue
            matched = any(close(a, dec, b, pct=suffix == "%") for b in (cited_pool if cited_pool else pool))
            if not matched and cited_pool:
                if any(close(a, dec, b, pct=suffix == "%") for b in pool):
                    res["checked"] += 1
                    res["issues"].append({"evidence": i, "claim": ev.get("claim"), "number": a, "problem": "other_file", "level": "unconfirmed",
                                          "plain": f"{a:g}{suffix} is in the recorded data, but not in the file cited ({', '.join(names)})."})
                    continue
            if suffix == "x" and not matched:
                continue  # a ratio the agent computed itself; the desk recomputes ratios anyway
            res["checked"] += 1
            if matched:
                res["matched"] += 1
            else:
                res["issues"].append({"evidence": i, "claim": ev.get("claim"), "number": a, "problem": "unconfirmed", "level": "unconfirmed",
                                      "plain": f"{a:g}{suffix} was cited as data but is not in any recorded pull for this debate (unconfirmed, may be a fresh pull that was not saved)."})
    if not has_fresh:  # agents may have used a live pull we never saw: a mismatch is then only unconfirmed
        for x in res["issues"]:
            if x["problem"] == "mismatch":
                x["level"] = "unconfirmed"
                x["plain"] += " The agent may have used a newer live pull that was not saved."
    res["wrong"] = sum(1 for x in res["issues"] if x["level"] == "wrong")
    res["unconfirmed"] = sum(1 for x in res["issues"] if x["level"] == "unconfirmed")
    return res


def run(folder, rnd):
    files = ["snapshot.json", "events.json", "levels.json", "optimizer.json", "regime.json", "context.json", "derivatives.json",
             "fundamentals.json"] + [f"desk_r{k}.json" for k in range(1, rnd + 1)]
    recorded = [load(os.path.join(folder, f)) for f in files]
    fresh_paths = sorted(glob.glob(os.path.join(folder, "fresh_*.json")))
    fresh = [load(p) for p in fresh_paths]
    extra = {os.path.basename(p): load(p) for p in sorted(glob.glob(os.path.join(folder, "tm_*.json")))}  # agents' own Time Machine runs
    by_name = {f: x for f, x in zip(files, recorded) if x}
    by_name.update({os.path.basename(p): x for p, x in zip(fresh_paths, fresh) if x})
    by_name.update({k: v for k, v in extra.items() if v})
    pulls = [x for x in [load(os.path.join(folder, "snapshot.json"))] + fresh if x]
    pool = leaves(list(by_name.values()), [])
    tfv = tf_values(pulls)
    out = {"round": rnd, "recorded_files": [f for f, x in zip(files, recorded) if x] + [f"fresh pulls: {len([f for f in fresh if f])}"]}
    for side in ("bull", "bear"):
        st = load(os.path.join(folder, f"r{rnd}_{side}.json"))
        out[side] = check_statement(st, pool, tfv, has_fresh=bool([f for f in fresh if f]), files=by_name) if st else {"checked": 0, "matched": 0, "issues": [], "wrong": 0, "unconfirmed": 0, "missing": True}
    with open(os.path.join(folder, f"claims_r{rnd}.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    summ = "; ".join(f"{s}: {out[s]['matched']}/{out[s]['checked']} confirmed, {out[s]['wrong']} wrong, {out[s]['unconfirmed']} unconfirmed" for s in ("bull", "bear"))
    audit(folder, "claims", f"round {rnd}: {summ}")
    return out, summ


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--round", type=int, required=True)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    out, summ = run(os.path.abspath(a.folder), a.round)
    print(f"wrote claims_r{a.round}.json: {summ}")
    for s in ("bull", "bear"):
        for i in out[s]["issues"]:
            print(f"  {s} evidence[{i['evidence']}]: {i['plain']}")


if __name__ == "__main__":
    main()
