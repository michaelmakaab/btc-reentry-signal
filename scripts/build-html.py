#!/usr/bin/env python3
"""
Bitcoin Re-Entry Signal v2 — Dashboard Builder
Generates a self-contained index.html with intuitive score flow.
"""

import json
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).parent.parent / "data"
OUT_FILE = Path(__file__).parent.parent / "index.html"


def main():
    data = json.load(open(DATA_DIR / "indicators.json"))
    c = data["_composite"]
    meta = data["_meta"]
    spark = data.get("_priceHistory", [])

    # Zone descriptions
    zone_descs = {
        "NO_ENTRY": "Market hasn't shown enough bottom signals yet. Most indicators say patience &mdash; there's likely more downside ahead.",
        "WATCHING": "Signals are building. Some indicators are entering historically attractive zones, but not enough confluence yet. Prepare capital and watch.",
        "ACCUMULATE": "Multiple domains signal value territory. History supports beginning measured accumulation (DCA). Not all signals have fired &mdash; the absolute bottom may not be in.",
        "STRONG_BUY": "Rare confluence across all domains. Historically, this level of signal convergence has marked cycle bottoms with near-perfect reliability."
    }

    # ── Domain Cards ──
    domain_icons = {"onChain": "&#9939;", "miner": "&#9935;", "technical": "&#128200;", "sentiment": "&#129504;", "exchange": "&#128178;", "cycle": "&#9202;"}
    domain_explainers = {
        "onChain": "Is Bitcoin cheap relative to its on-chain fundamentals? These metrics compare price to aggregate cost basis, network value, and holder behavior.",
        "miner": "Are miners under stress? Miner capitulation historically precedes price bottoms as weak miners exit and sell pressure drops.",
        "technical": "How far has price fallen from key levels? Deep drawdowns from ATH and major moving averages indicate oversold conditions.",
        "sentiment": "Is the market in panic? Extreme fear, negative funding, and sellers realizing losses are contrarian buy signals.",
        "exchange": "Where is the money flowing? Coins leaving exchanges and stablecoin buying power indicate accumulation.",
        "cycle": "Where are we in the ~4-year cycle? Historical timing patterns give context for when bottoms typically form."
    }

    domain_cards_html = ""
    for key, domain in c["domains"].items():
        sc = domain["score"]
        icon = domain_icons.get(key, "")
        explainer = domain_explainers.get(key, "")
        pct = int(domain["weight"] * 100)
        no_data = domain.get("noData", False)

        if no_data:
            sc_color = "#334155"
            score_html = '<span class="dscore-num" style="font-size:16px;color:#475569">Awaiting data</span>'
            subs = '<div style="color:#475569;font-size:12px;font-style:italic;padding:8px 0">Data will populate on the next scheduled fetch.</div>'
        else:
            sc_color = "#22C55E" if sc >= 7 else "#EAB308" if sc >= 5 else "#FB923C" if sc >= 3 else "#EF4444"
            score_html = f'<span class="dscore-num">{sc}</span><span class="dscore-max">/10</span>'
            # Sub-indicator bars
            subs = ""
            for item in domain["items"]:
                s = item["score"]
                ic = "#22C55E" if s >= 7 else "#EAB308" if s >= 5 else "#FB923C" if s >= 3 else "#EF4444"
                subs += f'''<div class="sub"><span class="sub-n">{item["name"]}</span><div class="bar-t"><div class="bar-f" style="width:{s*10}%;background:{ic}"></div></div><span class="sub-s" style="color:{ic}">{s}</span></div>'''

        domain_cards_html += f'''
        <div class="dcard"{' style="border-color:#1a2030"' if no_data else ''}>
          <div class="dcard-top">
            <div class="dcard-left">
              <span class="dicon">{icon}</span>
              <div>
                <div class="dname">{domain["label"]}</div>
                <div class="dweight">{pct}% of final score</div>
              </div>
            </div>
            <div class="dscore" style="color:{sc_color}">{score_html}</div>
          </div>
          <div class="dexplain">{explainer}</div>
          <div class="dsubs">{subs}</div>
        </div>'''

    # ── Key Readings ──
    def kv(label, val, color="#CBD5E1", note=""):
        note_html = f'<span class="kv-note">{note}</span>' if note else ""
        return f'<div class="kv"><div class="kv-label">{label}</div><div class="kv-val" style="color:{color}">{val}</div>{note_html}</div>'

    readings = ""
    p = meta["currentPrice"]

    # On-chain
    mz = data["mvrvZScore"]["value"]
    if mz is not None:
        mc = "#22C55E" if mz <= 0 else "#EAB308" if mz <= 1 else "#EF4444"
        readings += kv("MVRV-Z", f'{mz}', mc, "Below 0 = undervalued")

    nupl = data["nupl"]["value"]
    if nupl is not None:
        nc = "#22C55E" if nupl <= 0 else "#EAB308" if nupl <= 0.25 else "#FB923C"
        readings += kv("NUPL", f'{nupl}', nc, data["nupl"]["zone"] or "")

    rp = data["realizedPrice"]["value"]
    if rp is not None:
        readings += kv("Realized Price", f'${rp:,.0f}', "#22C55E", f'{data["realizedPrice"]["percentAbove"]}% above')

    sip = data["supplyInProfit"]["value"]
    if sip is not None:
        sc2 = "#22C55E" if sip <= 50 else "#EAB308" if sip <= 60 else "#FB923C"
        readings += kv("Supply in Profit", f'{sip}%', sc2, "Below 50% = bottom signal")

    rr = data["reserveRisk"]["value"]
    if rr is not None:
        rc = "#22C55E" if rr <= 0.002 else "#EAB308"
        readings += kv("Reserve Risk", f'{rr:.6f}', rc, "Green zone" if rr <= 0.002 else "")

    ssr_v = data["ssr"]["value"]
    if ssr_v is not None:
        readings += kv("Stablecoin Ratio", f'{ssr_v}', "#22C55E" if ssr_v <= 7 else "#EAB308", "Low = high buying power")

    # Technical
    mm = data["mayerMultiple"]["value"]
    if mm is not None:
        mc2 = "#22C55E" if mm <= 0.8 else "#EAB308"
        readings += kv("Mayer Multiple", f'{mm}', mc2, f'200d MA: ${data["mayerMultiple"]["sma200d"]:,.0f}')

    w2 = data["wma200"]
    if w2["value"]:
        readings += kv("200-Week MA", f'${w2["value"]:,.0f}', "#22C55E" if w2["ratio"] and w2["ratio"] <= 1.1 else "#EAB308", f'{w2["percentAbove"]}% above')

    pcb = data["piCycleBottom"]
    if pcb.get("signal"):
        pcb_c = "#22C55E" if pcb["signal"] == "BOTTOM SIGNAL" else "#EAB308" if pcb["signal"] == "APPROACHING" else "#64748B"
        pcb_note = f'150d EMA: ${pcb["ema150"]:,.0f}' if pcb.get("ema150") else ""
        readings += kv("Pi Cycle Bottom", pcb["signal"], pcb_c, pcb_note)

    readings += kv("Drawdown", f'{data["cycleTiming"]["drawdownPct"]}%', "#EAB308")
    readings += kv("Rainbow", data["rainbowChart"]["currentBand"], "#22C55E" if data["rainbowChart"]["currentBand"] in ["Fire Sale", "BUY!"] else "#EAB308")

    # Miner
    readings += kv("Hash Ribbon", data["hashRibbon"]["signal"] or "N/A", "#22C55E" if data["hashRibbon"]["signal"] == "BUY SIGNAL" else "#EAB308")
    pm = data["puellMultiple"]["value"]
    if pm: readings += kv("Puell Multiple", f'{pm}', "#22C55E" if pm <= 0.5 else "#EAB308")

    # Sentiment
    fg = data["fearGreed"]
    if fg["current"] is not None:
        fgc = "#22C55E" if fg["current"] <= 25 else "#EAB308"
        readings += kv("Fear & Greed", f'{fg["current"]}', fgc, f'{fg["label"]} ({fg["extremeFearDays"]}d streak)')

    if fg.get("extremeFearDays") is not None:
        fd_days = fg["extremeFearDays"]
        fd_c = "#22C55E" if fd_days >= 30 else "#EAB308" if fd_days >= 14 else "#64748B"
        readings += kv("Fear Duration", f'{fd_days} days', fd_c, "Consecutive extreme fear")

    sopr = data["sopr"]["value"]
    if sopr: readings += kv("SOPR", f'{sopr}', "#22C55E" if sopr <= 1.0 else "#FB923C")

    lth = data["lthSopr"]["value"]
    if lth: readings += kv("LTH-SOPR", f'{lth}', "#22C55E" if lth <= 1.0 else "#EAB308")

    fr = data["fundingRates"]["avg10d"]
    if fr is not None: readings += kv("Funding Rate", f'{fr}', "#22C55E" if fr < 0 else "#EAB308")

    # Exchange & Liquidity (show when data available)
    er = data.get("exchangeReserves", {}).get("value")
    if er is not None: readings += kv("Exchange Reserves", f'{er:,.0f} BTC', "#22C55E" if er < 2500000 else "#EAB308", "Declining = accumulation")

    enf = data.get("exchangeNetflow", {}).get("value")
    if enf is not None:
        enf_c = "#22C55E" if enf < 0 else "#EAB308"
        readings += kv("Exchange Netflow", f'{enf:,.0f} BTC', enf_c, "Negative = outflows")

    oi = data.get("openInterest", {}).get("value")
    if oi is not None: readings += kv("Open Interest", f'${oi:,.0f}', "#64748B")

    # Cycle
    ct = data["cycleTiming"]
    readings += kv("Cycle Progress", f'{int(ct["cycleProgress"]*100)}%', "#EAB308", f'Day {ct["daysSinceATH"]} of ~{ct["avgDaysToBottom"]}')
    readings += kv("Est. Bottom", ct["estimatedBottom"], "#94A3B8")

    # ── Spark data (use live price for last point) ──
    spark_data = [{"d": s["d"], "p": s["p"]} for s in spark[-90:]]
    if spark_data and meta["currentPrice"]:
        spark_data[-1]["p"] = round(meta["currentPrice"])
    spark_json = json.dumps(spark_data)

    # ── Score flow explanation (with individual indicators) ──
    has_empty = any(d.get("noData") for d in c["domains"].values())
    flow_items = ""
    for d in c["domains"].values():
        sc = d["score"]
        pct = round(d.get("effectiveWeight", d["weight"]) * 100)
        if d.get("noData"):
            orig_pct = int(d["weight"] * 100)
            flow_items += f'<div class="flow-row flow-domain"><span class="flow-name">{d["label"]}</span><span class="flow-score" style="color:#475569">&mdash;</span><span class="flow-x"></span><span class="flow-weight" style="color:#475569">{orig_pct}%</span><span class="flow-eq"></span><span class="flow-contrib" style="color:#475569;font-size:11px;width:auto">awaiting data*</span></div>'
            continue
        sc_c = "#22C55E" if sc >= 7 else "#EAB308" if sc >= 5 else "#FB923C" if sc >= 3 else "#EF4444"
        contrib = d.get("contribution", round(sc * d["weight"] * 10, 1))
        flow_items += f'<div class="flow-row flow-domain"><span class="flow-name">{d["label"]}</span><span class="flow-score" style="color:{sc_c}">{sc}/10</span><span class="flow-x">&times;</span><span class="flow-weight">{pct}%</span><span class="flow-eq">=</span><span class="flow-contrib">{contrib}</span></div>'
        for item in d["items"]:
            s = item["score"]
            ic = "#22C55E" if s >= 7 else "#EAB308" if s >= 5 else "#FB923C" if s >= 3 else "#EF4444"
            flow_items += f'<div class="flow-row flow-sub"><span class="flow-dot">&#8226;</span><span class="flow-name">{item["name"]}</span><span class="flow-score" style="color:{ic}">{s}/10</span></div>'
    if has_empty:
        flow_items += '<div class="flow-note">* Weight from empty domains is redistributed to active domains</div>'

    # ── Compose HTML ──
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bitcoin Re-Entry Signal</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,300;9..40,500;9..40,700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{min-height:100vh;background:#060911;color:#E2E8F0;font-family:'DM Sans',sans-serif;-webkit-font-smoothing:antialiased}}
.mono{{font-family:'Space Mono',monospace}}
.wrap{{max-width:1200px;margin:0 auto;padding:0 24px}}

/* Header */
.hdr{{background:linear-gradient(135deg,#0B1120,#0F172A,#0B1120);border-bottom:1px solid #1E293B;padding:24px 0}}
.hdr-inner{{display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:16px}}
.tag{{font-size:11px;color:#F59E0B;font-weight:700;letter-spacing:2px;text-transform:uppercase}}
.title{{font-size:26px;font-weight:700;color:#F8FAFC;margin-top:2px}}
.subtitle{{font-size:13px;color:#94A3B8;margin-top:4px}}
.price-box{{text-align:right}}
.price{{font-size:30px;font-weight:700;color:#F8FAFC}}
.pchange{{font-size:13px;color:#EF4444;margin-top:2px}}
.pdate{{font-size:11px;color:#475569;margin-top:2px}}

/* Gauge Section */
.gauge-sec{{display:flex;align-items:flex-start;gap:40px;padding:36px 0 24px;flex-wrap:wrap}}
.gauge-wrap{{position:relative;width:240px;height:240px;flex-shrink:0}}
.gauge-svg{{width:240px;height:240px}}
.gauge-mid{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center}}
.gauge-num{{font-size:52px;font-weight:700;line-height:1}}
.gauge-lbl{{font-size:13px;font-weight:700;letter-spacing:2px;margin-top:4px}}
.gauge-of{{font-size:11px;color:#64748B;margin-top:2px}}
.gauge-info{{flex:1;min-width:260px}}
.zone-name{{font-size:18px;font-weight:700;margin-bottom:8px}}
.zone-desc{{font-size:14px;color:#94A3B8;line-height:1.6;margin-bottom:16px}}
.zone-bar{{display:flex;border-radius:6px;overflow:hidden;height:10px;background:#1E293B}}
.zone-seg{{height:100%}}
.zone-labels{{display:flex;justify-content:space-between;font-size:10px;color:#475569;margin-top:4px}}
.zone-ptr{{height:10px;position:relative}}
.zone-needle{{position:absolute;top:-14px;width:2px;height:14px;background:#F8FAFC;border-radius:1px}}

/* Behind the Score — collapsible */
.methodology{{border-top:1px solid #1E293B;padding:16px 0}}
.methodology summary{{cursor:pointer;list-style:none;display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;color:#94A3B8;padding:8px 0;user-select:none}}
.methodology summary::-webkit-details-marker{{display:none}}
.methodology summary::before{{content:'';display:inline-block;width:0;height:0;border-left:5px solid #64748B;border-top:4px solid transparent;border-bottom:4px solid transparent;transition:transform .2s}}
.methodology[open] summary::before{{transform:rotate(90deg)}}
.methodology summary:hover{{color:#CBD5E1}}
.method-body{{padding:12px 0 4px;font-size:13px;color:#94A3B8;line-height:1.7}}
.method-body h4{{font-size:12px;color:#F59E0B;font-weight:700;letter-spacing:1px;text-transform:uppercase;margin:16px 0 6px}}
.method-body h4:first-child{{margin-top:4px}}
.method-body p{{margin-bottom:10px}}
.method-body ul{{margin:0 0 12px 18px}}
.method-body li{{margin-bottom:4px}}
.method-body .domain-row{{display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid #111827}}
.method-body .domain-row span:first-child{{color:#CBD5E1}}
.method-body .domain-row span:last-child{{color:#64748B;font-family:'Space Mono',monospace;font-size:12px}}

/* Flow: How score is calculated */
.flow-sec{{padding:20px 0;border-top:1px solid #1E293B}}
.flow-title{{font-size:12px;color:#64748B;letter-spacing:1px;text-transform:uppercase;margin-bottom:10px}}
.flow-row{{display:flex;align-items:center;gap:8px;padding:5px 0;font-size:13px}}
.flow-name{{width:200px;color:#94A3B8}}
.flow-score{{width:50px;font-weight:700}}
.flow-x,.flow-eq{{color:#475569;font-size:12px}}
.flow-weight{{width:40px;color:#64748B;text-align:center}}
.flow-contrib{{width:45px;font-weight:700;color:#CBD5E1;text-align:right}}
.flow-domain .flow-name{{color:#CBD5E1;font-weight:600}}
.flow-sub{{padding:2px 0}}
.flow-sub .flow-name{{padding-left:8px;color:#64748B;font-size:12px;width:192px}}
.flow-sub .flow-score{{font-size:12px;font-weight:600}}
.flow-dot{{color:#334155;font-size:10px;width:12px;flex-shrink:0}}
.flow-note{{font-size:11px;color:#475569;font-style:italic;padding:6px 0 2px}}
.flow-total{{display:flex;align-items:center;gap:8px;padding:8px 0;border-top:1px solid #1E293B;margin-top:4px;font-size:14px;font-weight:700}}

/* Sparkline */
.spark-sec{{padding:16px 0}}
.spark-box{{background:#0F172A;border:1px solid #1E293B;border-radius:10px;padding:16px;height:220px;position:relative;overflow:hidden}}
.spark-box canvas{{display:block}}
.spark-title{{font-size:11px;color:#475569;letter-spacing:0.5px;text-transform:uppercase;margin-bottom:8px}}

/* Domain Cards */
.dcards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px;padding:20px 0}}
.dcard{{background:#0F172A;border:1px solid #1E293B;border-radius:10px;padding:18px}}
.dcard:hover{{border-color:#334155}}
.dcard-top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}}
.dcard-left{{display:flex;align-items:center;gap:10px}}
.dicon{{font-size:22px}}
.dname{{font-size:14px;font-weight:700;color:#F8FAFC}}
.dweight{{font-size:11px;color:#475569}}
.dscore{{text-align:right}}
.dscore-num{{font-size:28px;font-weight:700}}
.dscore-max{{font-size:13px;color:#475569}}
.dexplain{{font-size:12px;color:#64748B;line-height:1.4;margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid #1E293B}}
.dsubs{{display:flex;flex-direction:column;gap:6px}}
.sub{{display:flex;align-items:center;gap:8px}}
.sub-n{{font-size:12px;color:#94A3B8;width:140px;flex-shrink:0}}
.bar-t{{flex:1;height:5px;background:#1E293B;border-radius:3px;overflow:hidden}}
.bar-f{{height:100%;border-radius:3px;transition:width .5s}}
.sub-s{{font-size:12px;width:24px;text-align:right;font-weight:700}}

/* Key Values */
.kv-sec{{padding:20px 0}}
.kv-title{{font-size:12px;color:#64748B;letter-spacing:1px;text-transform:uppercase;margin-bottom:10px}}
.kv-grid{{display:flex;flex-wrap:wrap;gap:8px}}
.kv{{background:#0F172A;border:1px solid #1E293B;border-radius:8px;padding:8px 14px}}
.kv-label{{font-size:10px;color:#475569;text-transform:uppercase;letter-spacing:0.5px}}
.kv-val{{font-size:15px;font-weight:700;margin-top:1px}}
.kv-note{{font-size:10px;color:#64748B;display:block}}

/* Section headers */
.sec-hdr{{font-size:12px;color:#64748B;letter-spacing:1px;text-transform:uppercase;padding-top:20px}}

/* Footer */
.footer{{border-top:1px solid #1E293B;margin-top:24px;padding:24px 0;font-size:11px;color:#475569;text-align:center;line-height:1.8}}
.footer a{{color:#64748B;text-decoration:none}}

@media(max-width:768px){{
  .gauge-sec{{gap:20px}}.gauge-wrap{{margin:0 auto}}.dcards{{grid-template-columns:1fr}}
  .hdr-inner{{flex-direction:column;align-items:flex-start}}.price-box{{text-align:left}}
  .flow-name{{width:120px}}
}}
</style>
</head>
<body>

<header class="hdr"><div class="wrap">
  <div class="hdr-inner">
    <div>
      <div class="tag">Bitcoin Re-Entry Signal</div>
      <div class="title">Cycle Bottom Detector</div>
      <div class="subtitle">26 indicators &bull; 6 domains &bull; 1 score</div>
    </div>
    <div class="price-box">
      <div class="price mono">${meta["currentPrice"]:,.0f}</div>
      <div class="pchange mono">{ct["drawdownPct"]}% from ATH (${ct["athPrice"]:,})</div>
      <div class="pdate">Updated {meta["computedAt"][:16].replace("T"," ")} UTC via {meta.get("priceSource","Blockchain.info")}</div>
    </div>
  </div>
</div></header>

<div class="wrap">

  <!-- Gauge + Zone -->
  <section class="gauge-sec">
    <div class="gauge-wrap">
      <svg class="gauge-svg" viewBox="0 0 240 240">
        <circle cx="120" cy="120" r="100" fill="none" stroke="#1E293B" stroke-width="12"
          stroke-dasharray="471 157" stroke-dashoffset="-78.5" stroke-linecap="round"/>
        <circle cx="120" cy="120" r="100" fill="none" stroke="{c["zoneColor"]}" stroke-width="12"
          stroke-dasharray="{c["score"]/100*471} {628-c["score"]/100*471}"
          stroke-dashoffset="-78.5" stroke-linecap="round"/>
      </svg>
      <div class="gauge-mid">
        <div class="gauge-num mono" style="color:{c["zoneColor"]}">{c["score"]}</div>
        <div class="gauge-lbl mono" style="color:{c["zoneColor"]}">{c["zoneLabel"]}</div>
        <div class="gauge-of mono">of 100</div>
      </div>
    </div>
    <div class="gauge-info">
      <div class="zone-name" style="color:{c["zoneColor"]}">{c["zoneLabel"]}</div>
      <div class="zone-desc">{zone_descs.get(c["zone"], "")}</div>
      <!-- Zone bar -->
      <div class="zone-bar">
        <div class="zone-seg" style="width:25%;background:#EF4444;opacity:0.4"></div>
        <div class="zone-seg" style="width:25%;background:#FB923C;opacity:0.4"></div>
        <div class="zone-seg" style="width:25%;background:#EAB308;opacity:0.4"></div>
        <div class="zone-seg" style="width:25%;background:#22C55E;opacity:0.4"></div>
      </div>
      <div class="zone-ptr"><div class="zone-needle" style="left:{c["score"]}%"></div></div>
      <div class="zone-labels mono">
        <span>0 No Entry</span><span>25 Watching</span><span>50 Accumulate</span><span>75 Strong Buy</span><span>100</span>
      </div>

    </div>
  </section>

  <!-- Behind the Score -->
  <details class="methodology">
    <summary>Behind the Score &mdash; Why These Metrics?</summary>
    <div class="method-body">
      <h4>The Problem</h4>
      <p>No single indicator reliably calls a Bitcoin cycle bottom. MVRV-Z can stay depressed for months. Fear &amp; Greed can flash extreme fear during a mid-cycle correction. The Puell Multiple can mislead during hash rate shifts. Every metric has blind spots.</p>

      <h4>The Approach</h4>
      <p>Instead of relying on any one signal, this model combines 26 indicators across 6 independent domains. The idea is simple: when enough unrelated metrics all say &ldquo;bottom,&rdquo; the signal is far more reliable than any individual reading. We&rsquo;re looking for <strong>confluence</strong> &mdash; the rare moments when on-chain, technical, sentiment, miner, exchange, and cycle data all align.</p>

      <h4>How Indicators Were Chosen</h4>
      <ul>
        <li><strong>On-Chain Valuation (30%)</strong> &mdash; MVRV-Z, NUPL, Realized Price, Reserve Risk, and others that compare market price to aggregate cost basis. These have marked every major cycle bottom in Bitcoin history.</li>
        <li><strong>Miner Health (15%)</strong> &mdash; Hash Ribbons and Puell Multiple track miner stress. When weak miners capitulate and sell pressure drops, bottoms tend to form.</li>
        <li><strong>Technical / Price (20%)</strong> &mdash; Mayer Multiple, 200-week MA, Pi Cycle, Rainbow Chart, and drawdown depth. These measure how far price has deviated from long-term means.</li>
        <li><strong>Sentiment &amp; Positioning (15%)</strong> &mdash; Fear &amp; Greed, SOPR, LTH-SOPR, and funding rates. Extreme fear and sellers realizing losses are classic contrarian signals.</li>
        <li><strong>Exchange &amp; Liquidity (10%)</strong> &mdash; Exchange reserves, netflow, open interest, and stablecoin ratios. Coins leaving exchanges and stablecoin dry powder signal accumulation.</li>
        <li><strong>Cycle Timing (10%)</strong> &mdash; Days since ATH, RHODL ratio, and historical cycle patterns. Context for whether we&rsquo;re in the typical bottoming window.</li>
      </ul>

      <h4>How the Score Works</h4>
      <p>Each indicator is scored 0&ndash;10 based on where its current value sits relative to historically confirmed bottom levels (10 = textbook bottom signal, 0 = nowhere near). Indicators within each domain are weighted by reliability, then domains are combined using the weights above. The final 0&ndash;100 composite maps to four zones:</p>
      <ul>
        <li><strong>0&ndash;25 No Entry</strong> &mdash; Not enough bottom signals. Patience.</li>
        <li><strong>25&ndash;50 Watching</strong> &mdash; Signals building, not enough confluence yet.</li>
        <li><strong>50&ndash;75 Accumulate</strong> &mdash; Multiple domains in value territory. DCA territory.</li>
        <li><strong>75&ndash;100 Strong Buy</strong> &mdash; Rare cross-domain confluence. Historically marks cycle bottoms.</li>
      </ul>

      <h4>Important Caveats</h4>
      <p>This is a framework, not financial advice. Past cycles don&rsquo;t guarantee future patterns. The model is designed for macro cycle bottoms &mdash; it won&rsquo;t help with short-term trading. Some BGeometrics indicators rotate through a cache due to API rate limits, so not all 26 indicators may be live at any given time. The score will become more accurate as all data populates.</p>
    </div>
  </details>

  <!-- How Score is Built (standalone section) -->
  <div class="flow-sec">
    <div class="flow-title">How the score is built</div>
    {flow_items}
    <div class="flow-total">
      <span class="flow-name">Composite Score</span>
      <span style="color:{c["zoneColor"]}">{c["score"]}/100</span>
    </div>
  </div>

  <!-- Sparkline -->
  <section class="spark-sec">
    <div class="spark-title">BTC Price &mdash; 90 Days</div>
    <div class="spark-box"><canvas id="spark"></canvas></div>
  </section>

  <!-- Domain Cards -->
  <div class="sec-hdr">Domain Breakdown</div>
  <section class="dcards">{domain_cards_html}</section>

  <!-- Key Values -->
  <section class="kv-sec">
    <div class="kv-title">All Indicator Readings</div>
    <div class="kv-grid">{readings}</div>
  </section>

</div>

<footer class="footer"><div class="wrap">
  <div>Bitcoin Re-Entry Signal v2 &mdash; Not financial advice. Do your own research.</div>
  <div>Data: BGeometrics &bull; Blockchain.info &bull; Alternative.me &bull; Binance</div>
  <div style="margin-top:6px"><a href="https://charts.bgeometrics.com/">BGeometrics</a> &bull; <a href="https://www.bitcoinmagazinepro.com/charts/">Bitcoin Magazine Pro</a> &bull; <a href="https://charts.bitbo.io/">Bitbo</a></div>
</div></footer>

<script>
const sd={spark_json};
const cv=document.getElementById('spark');
if(cv&&sd.length>0){{
const box=cv.parentElement;
const ctx=cv.getContext('2d');
const dpr=window.devicePixelRatio||1;
const pad=16;
const bw=box.clientWidth-pad*2, bh=box.clientHeight-pad*2;
cv.width=bw*dpr; cv.height=bh*dpr;
cv.style.width=bw+'px'; cv.style.height=bh+'px';
ctx.scale(dpr,dpr);
const w=bw, btm=20, h=bh-btm;
const pp=sd.map(d=>d.p);
const mn=Math.min(...pp)*0.97, mx=Math.max(...pp)*1.03, rng=mx-mn;
const mo=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function gx(i){{return(i/(sd.length-1))*w}}
function gy(p){{return h-((p-mn)/rng)*h}}

/* Grid lines + Y price labels */
ctx.strokeStyle='#1E293B'; ctx.lineWidth=1;
for(let i=0;i<=3;i++){{
  const y=(i/3)*h;
  ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(w,y); ctx.stroke();
  ctx.fillStyle='#475569'; ctx.font='10px Space Mono'; ctx.textAlign='left';
  ctx.fillText('$'+(mx-(i/3)*rng).toLocaleString(undefined,{{maximumFractionDigits:0}}),4,y+12);
}}

/* X date labels */
ctx.fillStyle='#475569'; ctx.font='10px Space Mono';
const step=Math.floor(sd.length/5);
ctx.textAlign='left';
const fd=sd[0].d.split('-');
ctx.fillText(mo[+fd[1]-1]+' '+parseInt(fd[2]),2,h+14);
ctx.textAlign='center';
for(let i=step;i<sd.length-step/2;i+=step){{
  const p=sd[i].d.split('-');
  ctx.fillText(mo[+p[1]-1]+' '+parseInt(p[2]),gx(i),h+14);
}}
ctx.textAlign='right';
const ld=sd[sd.length-1].d.split('-');
ctx.fillText(mo[+ld[1]-1]+' '+parseInt(ld[2]),w-2,h+14);

/* Price line */
ctx.beginPath(); ctx.strokeStyle='#EAB308'; ctx.lineWidth=2; ctx.lineJoin='round';
sd.forEach((d,i)=>{{const x=gx(i),y=gy(d.p); i===0?ctx.moveTo(x,y):ctx.lineTo(x,y)}});
ctx.stroke();

/* Gradient fill */
const gr=ctx.createLinearGradient(0,0,0,h);
gr.addColorStop(0,'rgba(234,179,8,0.12)'); gr.addColorStop(1,'rgba(234,179,8,0)');
ctx.lineTo(w,h); ctx.lineTo(0,h); ctx.closePath(); ctx.fillStyle=gr; ctx.fill();

/* End dot + current price label */
const ely=gy(pp[pp.length-1]);
ctx.beginPath(); ctx.arc(w-2,ely,4,0,Math.PI*2); ctx.fillStyle='#EAB308'; ctx.fill();
ctx.font='bold 11px Space Mono'; ctx.textAlign='right';
ctx.fillText('$'+pp[pp.length-1].toLocaleString(),w-12,ely>20?ely-8:ely+16);

/* Hover: crosshair, dot, tooltip */
const tip=document.createElement('div');
tip.style.cssText='position:absolute;display:none;background:#1E293B;border:1px solid #334155;border-radius:6px;padding:4px 8px;font:11px Space Mono;color:#E2E8F0;pointer-events:none;z-index:10;white-space:nowrap';
box.appendChild(tip);
const vl=document.createElement('div');
vl.style.cssText='position:absolute;display:none;width:1px;background:#334155;pointer-events:none;z-index:5';
box.appendChild(vl);
const hd=document.createElement('div');
hd.style.cssText='position:absolute;display:none;width:8px;height:8px;border-radius:50%;background:#EAB308;border:2px solid #0F172A;pointer-events:none;z-index:6;transform:translate(-50%,-50%)';
box.appendChild(hd);
cv.addEventListener('mousemove',e=>{{
  const r=cv.getBoundingClientRect();
  const idx=Math.round((e.clientX-r.left)/w*(sd.length-1));
  if(idx>=0&&idx<sd.length){{
    const d=sd[idx], p=d.d.split('-');
    const cx=gx(idx), cy=gy(d.p);
    tip.textContent=mo[+p[1]-1]+' '+parseInt(p[2])+', '+p[0]+'  $'+d.p.toLocaleString();
    vl.style.left=(cx+pad)+'px'; vl.style.top=pad+'px'; vl.style.height=h+'px';
    vl.style.display='block';
    hd.style.left=(cx+pad)+'px'; hd.style.top=(cy+pad)+'px';
    hd.style.display='block';
    tip.style.display='block';
    const tw=tip.offsetWidth;
    tip.style.left=Math.min(Math.max(cx+pad-tw/2,pad),w+pad-tw)+'px';
    tip.style.top=Math.max(cy+pad-28,pad)+'px';
  }}
}});
cv.addEventListener('mouseleave',()=>{{
  tip.style.display='none'; vl.style.display='none'; hd.style.display='none';
}});
}}
</script>
</body>
</html>'''

    with open(OUT_FILE, "w") as f:
        f.write(html)
    print(f"✓ Generated {OUT_FILE} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
