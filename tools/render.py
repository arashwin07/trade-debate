#!/usr/bin/env python3
"""Turn debate folders into the WhatsApp-style viewer pages.

  python tools/render.py debates/<id>   -> debates/<id>/debate.html   (single-file page, used for Claude artifacts)
                                           docs/d/<id>.html            (website copy, GitHub Pages)
                                           docs/index.html             (chat-list dashboard of every debate)
  python tools/render.py --index-only   -> rebuild docs/index.html only
  python tools/render.py --all          -> re-render every debate + the dashboard (after a UI change)

The design lives in tools/ui/debate.html and tools/ui/index.html. This script only collects the
debate's JSON files and injects them into those templates, so UI changes never touch the data.
"""
import json, os, sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEBATES = os.path.join(ROOT, "debates")
DOCS = os.path.join(ROOT, "docs")
UI = os.path.join(ROOT, "tools", "ui")
LEGACY = {"BUY": "TAKE", "SELL": "SKIP", "NO TRADE": "SKIP"}


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data["_written"] = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return data
    except Exception:
        return None


def config():
    return load(os.path.join(ROOT, "tools", "config.json")) or {}


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def decision(v):
    if not v:
        return None
    d = str(v.get("decision", "")).upper().strip()
    return LEGACY.get(d, d) if d else None


def collect(folder):
    meta = load(os.path.join(folder, "meta.json")) or {}
    snap = load(os.path.join(folder, "snapshot.json")) or {}
    rounds = []
    for n in (1, 2, 3):
        rounds.append({
            "n": n,
            "bull": load(os.path.join(folder, f"r{n}_bull.json")),
            "bear": load(os.path.join(folder, f"r{n}_bear.json")),
            "result": load(os.path.join(folder, f"r{n}_result.json")),
            "desk": load(os.path.join(folder, f"desk_r{n}.json")),
        })
    verdict = load(os.path.join(folder, "verdict.json"))
    return {
        "id": os.path.basename(folder.rstrip("/\\")),
        "mode": meta.get("mode", "named"),
        "scan_reason": meta.get("scan_reason"),
        "created_utc": meta.get("created_utc"),
        "trade": {
            "direction": str(meta.get("direction", "LONG")).upper(),
            "symbol": snap.get("symbol", meta.get("symbol")),
            "name": snap.get("name"),
            "market": snap.get("market", meta.get("market")),
            "style": snap.get("style", meta.get("style")),
            "user_plan": meta.get("user_plan"),
        },
        "snapshot": snap,
        "rounds": rounds,
        "verdict": verdict,
        "events": load(os.path.join(folder, "events.json")),
        "desk_final": load(os.path.join(folder, "desk_final.json")),
        "outcome": load(os.path.join(folder, "outcome.json")),
        "generated_utc": now(),
    }


def progress_text(d):
    for r in d["rounds"]:
        if not r["bull"] or not r["bear"]:
            return f"Round {r['n']} is being argued"
        if not r["result"]:
            return f"the Judge is reviewing Round {r['n']}"
    return "the Judge is making the final decision"


def inject(template, data, title):
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    with open(os.path.join(UI, template), encoding="utf-8") as f:
        html = f.read()
    return html.replace("__TITLE__", title).replace("__DATA__", blob)


def full_doc(fragment):
    head, body = fragment.split("</style>", 1)
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f"{head}</style></head><body>{body}</body></html>")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def render_debate(folder):
    cfg = config()
    d = collect(folder)
    t = d["trade"]
    title = f"{t['direction'].title()} {str(t['symbol'] or '').split('/')[0]} Debate"
    site = (cfg.get("site_url") or "").rstrip("/")
    # artifact copy: links back to the public dashboard, no auto-reload (the artifact is republished instead)
    d["links"] = {"dashboard": site + "/" if site else None}
    d["live_reload"] = False
    write(os.path.join(folder, "debate.html"), inject("debate.html", d, title))
    # website copy: relative link to the dashboard, reloads itself while the debate is still running
    d["links"] = {"dashboard": "../index.html"}
    d["live_reload"] = True
    write(os.path.join(DOCS, "d", d["id"] + ".html"), full_doc(inject("debate.html", d, title)))
    print("wrote", os.path.join(folder, "debate.html"))


def render_index():
    cfg = config()
    items = []
    if os.path.isdir(DEBATES):
        for name in sorted(os.listdir(DEBATES), reverse=True):
            folder = os.path.join(DEBATES, name)
            if not os.path.isdir(folder) or not os.path.exists(os.path.join(folder, "meta.json")):
                continue
            d = collect(folder)
            v = d["verdict"]
            dec = decision(v) or "LIVE"
            fin = d.get("desk_final") or {}
            out = d.get("outcome") or {}
            last_bear = next((r["bear"] for r in reversed(d["rounds"]) if r["bear"]), None)
            items.append({
                "id": d["id"], "href": f"d/{d['id']}.html",
                "symbol": d["trade"]["symbol"], "direction": d["trade"]["direction"],
                "market": d["trade"]["market"], "style": d["trade"]["style"], "mode": d["mode"],
                "created_utc": d["created_utc"], "decision": dec,
                "confidence": (v or {}).get("confidence"),
                "headline": (v or {}).get("headline_plain") or (v or {}).get("summary"),
                "progress": progress_text(d) if dec == "LIVE" else None,
                "preview": (last_bear or {}).get("headline"),
                "final_call": fin.get("final_call"), "gate": fin.get("gate"),
                "outcome": out.get("status"), "outcome_r": out.get("r"),
            })
    track = None
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import outcomes
        track = outcomes.summary()
    except Exception:
        pass
    data = {"debates": items, "generated_utc": now(), "schedule": cfg.get("schedule_plain"), "live_reload": True, "track": track}
    write(os.path.join(DOCS, "index.html"), full_doc(inject("index.html", data, "Trade Debate Desk")))
    print("wrote", os.path.join(DOCS, "index.html"))


def main():
    args = sys.argv[1:]
    if not args or args[0] == "--index-only":
        pass
    elif args[0] == "--all":
        for name in sorted(os.listdir(DEBATES)):
            folder = os.path.join(DEBATES, name)
            if os.path.isdir(folder) and os.path.exists(os.path.join(folder, "meta.json")):
                render_debate(folder)
    else:
        render_debate(os.path.abspath(args[0]))
    render_index()


if __name__ == "__main__":
    main()
