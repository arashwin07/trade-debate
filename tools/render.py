#!/usr/bin/env python3
"""Render debate folders into readable HTML pages.

  python tools/render.py debates/<id>     -> debates/<id>/debate.html (artifact page)
                                             docs/d/<id>.html          (website copy)
                                             docs/index.html           (dashboard of all debates)
  python tools/render.py --index-only     -> rebuild docs/index.html

The docs/ folder can be served by GitHub Pages so debates are viewable from any device.
"""
import html, json, os, sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEBATES = os.path.join(ROOT, "debates")
DOCS = os.path.join(ROOT, "docs")
ROUND_NAMES = {1: "Opening", 2: "Rebuttal", 3: "Closing"}

FONTS = '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;700;800&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">'

CSS = """
/* Layout: summary-first trading desk. Verdict on top, then the debate as a two-lane timeline (Bull left, Bear right). */
:root{
  --bg:#f3f5f7; --panel:#ffffff; --ink:#18202a; --muted:#5d6b7a; --line:#dde3ea;
  --bull:#0f8a5f; --bull-soft:#e3f4ec; --bear:#c6363b; --bear-soft:#fbe7e7;
  --judge:#9a6a00; --judge-soft:#fbf1d9; --link:#1f5fae;
  --f-display:"Archivo","Arial Narrow",system-ui,sans-serif;
  --f-body:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  --f-mono:"IBM Plex Mono",ui-monospace,Consolas,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#0f141a; --panel:#171e26; --ink:#e6ebf0; --muted:#93a1b0; --line:#2a3440;
  --bull:#3ccf95; --bull-soft:#12302a; --bear:#ff7a7f; --bear-soft:#3a1c20;
  --judge:#f0bf4c; --judge-soft:#352a12; --link:#7fb2ff; color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#0f141a; --panel:#171e26; --ink:#e6ebf0; --muted:#93a1b0; --line:#2a3440;
  --bull:#3ccf95; --bull-soft:#12302a; --bear:#ff7a7f; --bear-soft:#3a1c20;
  --judge:#f0bf4c; --judge-soft:#352a12; --link:#7fb2ff; color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font:15px/1.55 var(--f-body);margin:0}
.wrap{max-width:1120px;margin:0 auto;padding-block:28px 64px;
  padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));
  display:grid;gap:28px}
a{color:var(--link)} a:focus-visible,button:focus-visible{outline:2px solid var(--link);outline-offset:2px}
h1,h2,h3{font-family:var(--f-display);margin:0;text-wrap:balance;letter-spacing:-.01em}
h2{font-size:1.25rem}
.eyebrow{font:500 .72rem/1 var(--f-mono);text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.mono,.num{font-family:var(--f-mono);font-variant-numeric:tabular-nums}
.muted{color:var(--muted)}
.chip{display:inline-flex;align-items:center;gap:6px;padding:3px 9px;border-radius:999px;font:500 .75rem/1.4 var(--f-mono);
  border:1px solid var(--line);background:var(--panel);white-space:nowrap}
.chip.bull{color:var(--bull);border-color:currentColor;background:var(--bull-soft)}
.chip.bear{color:var(--bear);border-color:currentColor;background:var(--bear-soft)}
.chip.judge{color:var(--judge);border-color:currentColor;background:var(--judge-soft)}
.top{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:16px}
.top h1{font-size:clamp(1.9rem,5vw,2.8rem);font-weight:800}
.quote{display:flex;flex-wrap:wrap;gap:6px 18px;align-items:baseline}
.quote .px{font:600 1.6rem/1 var(--f-mono)}
.up{color:var(--bull)} .down{color:var(--bear)}
.meta{display:flex;flex-wrap:wrap;gap:8px}

/* verdict */
.verdict{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.verdict-head{display:grid;grid-template-columns:auto 1fr;gap:20px;padding:22px;align-items:center;border-bottom:1px solid var(--line)}
.stamp{font:800 clamp(1.6rem,4.5vw,2.4rem)/1 var(--f-display);padding:14px 20px;border-radius:10px;border:3px solid currentColor;
  text-transform:uppercase;letter-spacing:.02em;text-align:center;min-width:150px}
.stamp.TAKE{color:var(--bull);background:var(--bull-soft)} .stamp.SKIP{color:var(--bear);background:var(--bear-soft)}
.stamp.PENDING{color:var(--judge);background:var(--judge-soft)}
.trade-banner{display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 18px}
.trade-banner .t{font:800 1.35rem/1.1 var(--f-display)}
.dir{font:700 .8rem/1 var(--f-mono);padding:6px 10px;border-radius:6px;letter-spacing:.06em}
.dir.LONG{color:var(--bull);background:var(--bull-soft)} .dir.SHORT{color:var(--bear);background:var(--bear-soft)}
.flaws{margin:0;padding-left:18px;font-size:.87rem}
.stamp small{display:block;font:500 .72rem/1.4 var(--f-mono);letter-spacing:.06em;margin-top:6px}
.verdict-head p{margin:6px 0 0;max-width:68ch;font-size:1.02rem}
.conf{height:8px;border-radius:99px;background:var(--line);overflow:hidden;max-width:320px;margin-top:10px}
.conf span{display:block;height:100%;background:var(--judge)}
.verdict-body{display:grid;grid-template-columns:1.1fr 1fr;gap:0}
.verdict-body>section{padding:20px 22px;min-width:0}
.verdict-body>section+section{border-left:1px solid var(--line)}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:6px 16px;margin:12px 0 0}
.kv dt{color:var(--muted);font-size:.85rem} .kv dd{margin:0;font-family:var(--f-mono);font-variant-numeric:tabular-nums}
.score{display:grid;gap:10px;margin-top:12px}
.score-row{display:grid;grid-template-columns:120px 1fr 1fr;gap:10px;align-items:center;font-size:.85rem}
.bar{height:10px;background:var(--line);border-radius:99px;position:relative;overflow:hidden}
.bar span{position:absolute;top:0;bottom:0;border-radius:99px}
.bar.b span{left:0;background:var(--bull)} .bar.r span{left:0;background:var(--bear)}
.score-total{display:flex;justify-content:space-between;font:600 1rem var(--f-mono);margin-top:4px}
.prose p{margin:0 0 10px;max-width:70ch}
ul.plain{margin:6px 0 0;padding-left:18px}

/* debate timeline */
.round{display:grid;gap:12px}
.round-label{display:flex;align-items:center;gap:12px}
.round-label .n{font:700 .8rem/1 var(--f-mono);border:1px solid var(--line);border-radius:6px;padding:5px 8px;background:var(--panel)}
.lanes{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.speech{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px;min-width:0;display:grid;gap:10px;align-content:start}
.speech.bull{border-top:4px solid var(--bull)} .speech.bear{border-top:4px solid var(--bear)}
.who{display:flex;justify-content:space-between;align-items:center;gap:8px}
.who b{font-family:var(--f-display);font-size:1.05rem}
.speech h3{font-size:1.02rem;font-weight:700;line-height:1.35}
.speech .prose p{font-size:.93rem}
details{border-top:1px dashed var(--line);padding-top:8px}
summary{cursor:pointer;font:500 .8rem var(--f-mono);color:var(--muted)}
.ev{list-style:none;margin:8px 0 0;padding:0;display:grid;gap:8px}
.ev li{font-size:.87rem;display:grid;gap:2px}
.ev .src{font:400 .74rem/1.4 var(--f-mono);color:var(--muted);overflow-wrap:anywhere}
.reb{display:grid;gap:8px;margin-top:8px}
.reb div{font-size:.87rem;border-left:3px solid var(--line);padding-left:10px}
.reb em{color:var(--muted);font-style:normal;display:block;font-size:.8rem}
.plan{font:400 .8rem/1.5 var(--f-mono);background:var(--bg);border-radius:8px;padding:8px 10px;overflow-wrap:anywhere}

/* tables */
.tbl{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:12px}
table{border-collapse:collapse;width:100%;font-size:.86rem}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
th{font:500 .72rem var(--f-mono);text-transform:uppercase;letter-spacing:.06em;color:var(--muted);white-space:nowrap}
tr:last-child td{border-bottom:0}
td.num{white-space:nowrap}
.st{font:500 .72rem var(--f-mono);padding:2px 7px;border-radius:5px;white-space:nowrap}
.st.verified{color:var(--bull);background:var(--bull-soft)} .st.wrong{color:var(--bear);background:var(--bear-soft)}
.st.stale,.st.unverifiable{color:var(--judge);background:var(--judge-soft)}
.news{display:grid;gap:8px;grid-template-columns:repeat(auto-fill,minmax(280px,1fr))}
.news a{display:block;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;text-decoration:none;color:var(--ink);font-size:.88rem;min-width:0}
.news a:hover{border-color:var(--link)}
.news span{display:block;font:400 .72rem var(--f-mono);color:var(--muted);margin-top:4px}
.disc{font-size:.8rem;color:var(--muted);border-top:1px solid var(--line);padding-top:14px}
.pending{padding:22px;color:var(--muted)}
@media (max-width:760px){
  .lanes,.verdict-body{grid-template-columns:1fr}
  .verdict-body>section+section{border-left:0;border-top:1px solid var(--line)}
  .verdict-head{grid-template-columns:1fr}
  .score-row{grid-template-columns:90px 1fr 1fr}
}
@media (prefers-reduced-motion:no-preference){.conf span,.bar span{transition:width .6s ease}}
"""

e = lambda x: html.escape(str(x if x is not None else ""))


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def paras(text):
    return "".join(f"<p>{e(p.strip())}</p>" for p in str(text or "").split("\n\n") if p.strip())


def fmt_num(x):
    if isinstance(x, (int, float)):
        return f"{x:,.6f}".rstrip("0").rstrip(".") if abs(x) < 1 else f"{x:,.2f}"
    return e(x)


def link(url, text):
    return f'<a href="{e(url)}" target="_blank" rel="noopener">{e(text)}</a>' if url else e(text)


LEGACY = {"BUY": "TAKE", "SELL": "SKIP", "NO TRADE": "SKIP"}  # first demo used BUY/SELL/NO TRADE


def norm_decision(v):
    d = str((v or {}).get("decision", "PENDING")).upper().strip()
    return LEGACY.get(d, d) if d in ("TAKE", "SKIP", "PENDING") or d in LEGACY else d


def speech(d, side):
    name = "Bull Claude" if side == "bull" else "Bear Claude"
    role = "FOR the trade" if side == "bull" else "AGAINST the trade"
    if not d:
        return f'<article class="speech {side}"><div class="who"><b>{name}</b></div><p class="muted">No statement filed for this round.</p></article>'
    ev = "".join(
        f'<li><span>{e(x.get("claim"))}</span><span class="src">{e(x.get("value"))} · {link(x.get("url"), x.get("source"))} · {e(x.get("time"))}</span></li>'
        for x in d.get("evidence") or [])
    reb = "".join(f'<div><em>{e(x.get("opponent_point"))}</em>{e(x.get("response"))}</div>' for x in d.get("rebuttals") or [])
    p = d.get("plan") or {}
    plan = " · ".join(f"{k.replace('_', ' ')}: {', '.join(v) if isinstance(v, list) else v}" for k, v in p.items() if v)
    flaws = "".join(f"<li>{e(x)}</li>" for x in d.get("plan_flaws") or [])
    recon = d.get("conditions_to_reconsider")
    return f"""<article class="speech {side}">
  <div class="who"><b>{name}</b><span class="chip {side}">{role}</span></div>
  <h3>{e(d.get('headline'))}</h3>
  <div class="prose">{paras(d.get('argument'))}</div>
  {f'<div class="reb">{reb}</div>' if reb else ''}
  {f'<div class="plan">{"Trade plan" if side == "bull" else "Bear alternative"} · {e(plan)}</div>' if plan else ''}
  {f'<div><div class="eyebrow">Flaws in the plan</div><ul class="flaws">{flaws}</ul></div>' if flaws else ''}
  {f'<div class="plan">Would reconsider if: {e(recon)}</div>' if recon else ''}
  <details><summary>Evidence ({len(d.get('evidence') or [])})</summary><ul class="ev">{ev}</ul></details>
</article>"""


def scorebars(sc):
    b, r = sc.get("bull") or {}, sc.get("bear") or {}
    rows = ""
    for k in ["evidence_quality", "data_accuracy", "rebuttal_strength", "plan_reasoning"]:
        bv = b.get(k, b.get("plan_quality", 0) if k == "plan_reasoning" else 0) or 0
        rv = r.get(k, r.get("plan_quality", 0) if k == "plan_reasoning" else 0) or 0
        rows += f'<div class="score-row"><span class="muted">{k.replace("_", " ").capitalize()}</span>' \
                f'<div class="bar b" title="Bull {bv}/10"><span style="width:{bv*10}%"></span></div>' \
                f'<div class="bar r" title="Bear {rv}/10"><span style="width:{rv*10}%"></span></div></div>'
    return f"""<div class="score"><div class="score-row"><span></span><span class="eyebrow up">Bull</span><span class="eyebrow down">Bear</span></div>{rows}
<div class="score-total"><span class="up">Bull {e(b.get('total'))}/40</span><span class="down">Bear {e(r.get('total'))}/40</span></div></div>"""


def verdict_block(v):
    if not v:
        return '<section class="verdict"><div class="pending">The Judge has not ruled yet. Debate in progress.</div></section>'
    dec = norm_decision(v)
    cls = dec if dec in ("TAKE", "SKIP") else "PENDING"
    tp = v.get("trade_plan") or {}
    kv = "".join(f"<dt>{e(k.replace('_', ' ').capitalize())}</dt><dd>{e(', '.join(val) if isinstance(val, list) else val)}</dd>"
                 for k, val in tp.items() if val)
    risks = "".join(f"<li>{e(x)}</li>" for x in v.get("key_risks") or [])
    plan_title = "Trade plan" if dec == "TAKE" else "The trade that was proposed"
    cond_title, cond = ("Invalidation", v.get("invalidation")) if dec == "TAKE" else \
        ("What would make it worth taking", v.get("retake_conditions") or v.get("invalidation"))
    return f"""<section class="verdict" aria-label="Judge verdict">
  <div class="verdict-head">
    <div class="stamp {cls}">{e(dec)}<small>{'Take the trade' if dec == 'TAKE' else 'Skip the trade' if dec == 'SKIP' else "Judge's ruling"}</small></div>
    <div><div class="eyebrow">Confidence {e(v.get('confidence'))}% · winner: {e(v.get('winner'))}</div>
      <div class="conf"><span style="width:{int(v.get('confidence') or 0)}%"></span></div>
      <p>{e(v.get('summary'))}</p></div>
  </div>
  <div class="verdict-body">
    <section><h2>{plan_title}</h2><dl class="kv">{kv}</dl>
      <h2 style="margin-top:18px">{cond_title}</h2><p class="mono" style="margin:6px 0 0;font-size:.88rem">{e(cond)}</p></section>
    <section><h2>Scorecard</h2>{scorebars(v.get('scorecard') or {})}
      <h2 style="margin-top:18px">Key risks</h2><ul class="plain">{risks}</ul></section>
  </div>
  <div class="verdict-body"><section style="grid-column:1/-1"><h2>Why the Judge ruled this way</h2><div class="prose" style="margin-top:8px">{paras(v.get('reasoning'))}</div>
    <p class="muted mono" style="font-size:.78rem;margin:0">{e(v.get('data_freshness'))}</p></section></div>
</section>"""


def tf_table(snap):
    rows = ""
    for t in snap.get("timeframes") or []:
        if t.get("error"):
            continue
        m = t.get("macd") or {}
        rows += f"<tr><td class='num'>{e(t['timeframe'])}</td><td class='num'>{fmt_num(t.get('close'))}</td><td class='num'>{e(t.get('rsi14'))}</td>" \
                f"<td class='num'>{fmt_num(m.get('histogram'))}</td><td class='num'>{fmt_num(t.get('ema9'))} / {fmt_num(t.get('ema21'))}</td>" \
                f"<td class='num'>{fmt_num(t.get('atr14'))}</td><td class='num'>{e(t.get('volume_vs_20avg'))}x</td>" \
                f"<td class='num'>{fmt_num(t.get('recent_low_50'))} – {fmt_num(t.get('recent_high_50'))}</td><td>{e('; '.join(t.get('trend_facts') or []))}</td></tr>"
    return f"""<div class="tbl"><table><thead><tr><th>TF</th><th>Close</th><th>RSI 14</th><th>MACD hist</th><th>EMA 9 / 21</th><th>ATR 14</th><th>Vol vs avg</th><th>50-bar range</th><th>Trend facts</th></tr></thead><tbody>{rows}</tbody></table></div>"""


def checks_table(v):
    rows = "".join(
        f"<tr><td><span class='chip {e(c.get('by'))}'>{e(c.get('by'))} R{e(c.get('round'))}</span></td><td>{e(c.get('claim'))}</td>"
        f"<td><span class='st {e(str(c.get('status')).lower())}'>{e(c.get('status'))}</span></td><td class='muted'>{e(c.get('note'))}</td></tr>"
        for c in (v or {}).get("claim_checks") or [])
    if not rows:
        return ""
    return f"""<section style="display:grid;gap:12px"><h2>Judge's fact check</h2><div class="tbl"><table><thead><tr><th>By</th><th>Claim</th><th>Status</th><th>Note</th></tr></thead><tbody>{rows}</tbody></table></div></section>"""


def debate_page(folder):
    meta = load(os.path.join(folder, "meta.json")) or {}
    snap = load(os.path.join(folder, "snapshot.json")) or {}
    v = load(os.path.join(folder, "verdict.json"))
    direction = str(meta.get("direction", "LONG")).upper()
    chg = snap.get("change_24h_pct", snap.get("change_today_pct"))
    chg_lbl = "24h" if "change_24h_pct" in snap else "today"
    rounds = ""
    for n in (1, 2, 3):
        b, r = load(os.path.join(folder, f"r{n}_bull.json")), load(os.path.join(folder, f"r{n}_bear.json"))
        if not b and not r:
            continue
        rounds += f"""<section class="round"><div class="round-label"><span class="n">R{n}</span><h2>{ROUND_NAMES[n]}</h2></div>
<div class="lanes">{speech(b, 'bull')}{speech(r, 'bear')}</div></section>"""
    news = "".join(f'<a href="{e(x.get("url"))}" target="_blank" rel="noopener">{e(x.get("title"))}<span>{e(x.get("source"))} · {e(x.get("published"))}</span></a>'
                   for x in (snap.get("news") or [])[:12] if x.get("title"))
    extra = []
    if isinstance(snap.get("fear_greed_index"), dict) and "value" in snap["fear_greed_index"]:
        f = snap["fear_greed_index"]; extra.append(f"Fear & Greed {f['value']} ({f['label']})")
    if isinstance(snap.get("order_book_top100"), dict) and snap["order_book_top100"].get("bid_ask_ratio"):
        extra.append(f"Bid/ask depth {snap['order_book_top100']['bid_ask_ratio']}")
    if isinstance(snap.get("perp_funding_rate_pct"), (int, float)):
        extra.append(f"Funding {snap['perp_funding_rate_pct']}%")
    title = f"{snap.get('symbol', meta.get('symbol', 'Trade'))} Debate"
    body = f"""<title>{e(title)}</title>
<meta name="claude:viewport-fit-sides" content="cover">
{FONTS}<style>{CSS}</style>
<main class="wrap">
  <header class="top">
    <div><div class="eyebrow">{e((snap.get('market') or meta.get('market') or '').upper())} · {e(snap.get('style', meta.get('style')))} · {e(meta.get('mode', 'named'))} mode · {e(snap.get('data_source'))}</div>
      <h1>{e(snap.get('symbol', meta.get('symbol')))} {f'<span class="muted" style="font-size:.5em;font-weight:500">{e(snap.get("name"))}</span>' if snap.get('name') else ''}</h1></div>
    <div style="display:grid;gap:8px;justify-items:end">
      <div class="quote"><span class="px">{fmt_num(snap.get('price'))}</span>{f'<span class="num {"up" if (chg or 0) >= 0 else "down"}">{chg:+.2f}% {chg_lbl}</span>' if isinstance(chg, (int, float)) else ''}</div>
      <div class="meta"><span class="chip">{e(snap.get('market_status'))}</span><span class="chip">Snapshot {e(snap.get('snapshot_utc'))}</span>{''.join(f'<span class="chip">{e(x)}</span>' for x in extra)}</div>
    </div>
  </header>
  <section class="trade-banner" aria-label="Proposed trade"><span class="eyebrow">Proposed trade</span>
    <span class="dir {e(direction)}">{e(direction)}</span><span class="t">{e(snap.get('symbol', meta.get('symbol')))}</span>
    <span class="muted">Bull Claude argues to take it · Bear Claude argues to skip it · the Judge decides</span>
    {f'<span class="muted">Picked by the scanner: {e(meta.get("scan_reason"))}</span>' if meta.get('scan_reason') else ''}</section>
  {verdict_block(v)}
  <section style="display:grid;gap:12px"><h2>Live evidence both sides argued from</h2>{tf_table(snap)}</section>
  {rounds}
  {checks_table(v)}
  {f'<section style="display:grid;gap:12px"><h2>Headlines in the snapshot</h2><div class="news">{news}</div></section>' if news else ''}
  <p class="disc">Bull Claude (for the trade) and Bear Claude (against the trade) argue fixed sides by design. The Judge's TAKE or SKIP ruling is AI analysis of public market data and news. It is not licensed financial advice, prices may be delayed, and this workflow never places orders. You make and execute your own trades.</p>
</main>"""
    return title, body


def full_doc(title, body):
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">{body.split("</style>", 1)[0]}</style></head><body>{body.split("</style>", 1)[1]}</body></html>'


def index_page():
    rows = []
    if os.path.isdir(DEBATES):
        for d in sorted(os.listdir(DEBATES), reverse=True):
            f = os.path.join(DEBATES, d)
            if not os.path.isdir(f):
                continue
            meta = load(os.path.join(f, "meta.json")) or {}
            snap = load(os.path.join(f, "snapshot.json")) or {}
            v = load(os.path.join(f, "verdict.json")) or {}
            dec = norm_decision(v) if v else "PENDING"
            cls = "bull" if dec == "TAKE" else "bear" if dec == "SKIP" else "judge"
            trade = f"{str(meta.get('direction', 'LONG')).upper()} {snap.get('symbol', meta.get('symbol'))}"
            rows.append(f"<tr><td class='num'>{e(meta.get('created_utc', d))}</td><td><a href='d/{e(d)}.html'><b>{e(trade)}</b></a></td>"
                        f"<td>{e(snap.get('market'))}</td><td>{e(snap.get('style'))}</td><td>{e(meta.get('mode'))}</td><td class='num'>{fmt_num(snap.get('price'))}</td>"
                        f"<td><span class='chip {cls}'>{e(dec)}</span></td><td class='num'>{e(v.get('confidence', ''))}%</td><td class='muted'>{e(v.get('summary', ''))}</td></tr>")
    body = f"""<title>Trade Debate Desk</title>
<meta name="claude:viewport-fit-sides" content="cover">
{FONTS}<style>{CSS}</style>
<main class="wrap">
  <header class="top"><div><div class="eyebrow">Bull Claude (for) vs Bear Claude (against) · the Judge decides TAKE or SKIP</div><h1>Trade Debate Desk</h1></div>
  <span class="chip">Updated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</span></header>
  <div class="tbl"><table><thead><tr><th>Time (UTC)</th><th>Proposed trade</th><th>Market</th><th>Style</th><th>Mode</th><th>Price</th><th>Ruling</th><th>Conf.</th><th>Summary</th></tr></thead>
  <tbody>{''.join(rows) or '<tr><td colspan="9" class="muted">No debates yet. Run /trade-debate or /trade-scan.</td></tr>'}</tbody></table></div>
  <p class="disc">AI analysis of public data. Not financial advice. No orders are placed.</p>
</main>"""
    return body


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    args = sys.argv[1:]
    if args and args[0] != "--index-only":
        folder = os.path.abspath(args[0])
        did = os.path.basename(folder.rstrip("/\\"))
        title, body = debate_page(folder)
        write(os.path.join(folder, "debate.html"), body)
        write(os.path.join(DOCS, "d", did + ".html"), full_doc(title, body))
        print("wrote", os.path.join(folder, "debate.html"))
    write(os.path.join(DOCS, "index.html"), full_doc("Trade Debate Desk", index_page()))
    print("wrote", os.path.join(DOCS, "index.html"))


if __name__ == "__main__":
    main()
