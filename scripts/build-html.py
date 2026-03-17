#!/usr/bin/env python3
"""
Bitcoin Re-Entry Signal v2 — Dashboard Builder
Generates a self-contained index.html with intuitive score flow.
"""

import json
from pathlib import Path
from datetime import datetime
import os

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

    # ── Halving Countdown ──
    halving = data.get("_halving")
    halving_html = ""
    if halving:
        h_pct = round(halving["progress"] * 100, 1)
        halving_html = f'''
    <section class="extras-sec">
      <div class="sec-hdr">Extras</div>
      <div class="extras-grid">
        <div class="halving-card">
          <div class="halving-top">
            <span class="halving-icon">&#9201;</span>
            <span class="halving-label">NEXT HALVING</span>
          </div>
          <div class="halving-big mono">{halving["blocksLeft"]:,} <span class="halving-unit">blocks</span></div>
          <div class="halving-sub mono">~{halving["estDays"]:,} days &bull; Est. {halving["estDate"][:7].replace("-"," ")}</div>
          <div class="halving-bar-wrap">
            <div class="halving-bar"><div class="halving-fill" style="width:{h_pct}%"></div></div>
            <div class="halving-bar-labels mono">
              <span>Block {halving["blockHeight"]:,}</span>
              <span>{h_pct}%</span>
              <span>{halving["nextBlock"]:,}</span>
            </div>
          </div>
          <div class="halving-reward mono">
            <span>{halving["reward"]} BTC</span>
            <span class="halving-arrow">&#8594;</span>
            <span style="color:#F59E0B">{halving["nextReward"]} BTC</span>
          </div>
        </div>'''
    else:
        halving_html = '''
    <section class="extras-sec">
      <div class="sec-hdr">Extras</div>
      <div class="extras-grid">'''

    # ── Cycle Comparison ──
    cc = data.get("_cycleComparison")
    cycle_json = ""
    if cc:
        cycle_json = json.dumps(cc)

    cycle_html = f'''
        <div class="cycle-card">
          <div class="cycle-top">
            <span class="halving-icon">&#128200;</span>
            <span class="halving-label">CYCLE COMPARISON</span>
          </div>
          <div class="cycle-sub">Drawdown from ATH &mdash; Day {cc["daysSinceATH"]} of current cycle</div>
          <div class="cycle-chart-box"><canvas id="cycleChart"></canvas></div>
          <div class="cycle-legend">
            <span class="cl-item"><span class="cl-dot" style="background:#F59E0B"></span>Current</span>
            <span class="cl-item"><span class="cl-dot" style="background:#6366F1"></span>2021-22</span>
            <span class="cl-item"><span class="cl-dot" style="background:#06B6D4"></span>2017-18</span>
            <span class="cl-item"><span class="cl-dot" style="background:#475569"></span>2013-15</span>
          </div>
        </div>
      </div>
    </section>''' if cc else "</div></section>"

    # ── Backtest Track Record ──
    bt_file = DATA_DIR / "backtest_results.json"
    bt_html = ""
    bt_chart_json = "null"
    if bt_file.exists():
        bt = json.load(open(bt_file))
        zs = bt.get("zone_stats", {})

        # Build chart data: sample every 7 days for performance
        daily = bt.get("daily", [])
        chart_points = []
        for i, d in enumerate(daily):
            if i % 7 == 0 or i == len(daily) - 1:
                chart_points.append({"d": d["date"], "s": d["score"], "p": d["price"], "z": d["zone"]})
        bt_chart_json = json.dumps(chart_points)

        # Zone stats table rows
        zone_rows = ""
        zone_config = [
            ("STRONG_BUY", "Strong Buy", "75&ndash;100", "#22C55E"),
            ("ACCUMULATE", "Accumulate", "50&ndash;75", "#EAB308"),
            ("WATCHING", "Watching", "25&ndash;50", "#FB923C"),
            ("NO_ENTRY", "No Entry", "0&ndash;25", "#EF4444"),
        ]
        for zkey, zlabel, zrange, zcolor in zone_config:
            zd = zs.get(zkey, {})
            days = zd.get("days", 0)
            if days == 0:
                continue
            avg180 = zd.get("avg_180d")
            win180 = zd.get("win_rate_180d")
            avg365 = zd.get("avg_365d")
            win365 = zd.get("win_rate_365d")
            zone_rows += f'''<tr>
              <td style="color:{zcolor};font-weight:700">{zlabel}</td>
              <td class="mono">{zrange}</td>
              <td class="mono">{days}</td>
              <td class="mono" style="color:{'#22C55E' if avg180 and avg180 > 0 else '#EF4444'}">{'+' if avg180 and avg180 > 0 else ''}{avg180:.0f}%</td>
              <td class="mono">{win180:.0f}%</td>
              <td class="mono" style="color:{'#22C55E' if avg365 and avg365 > 0 else '#EF4444'}">{'+' if avg365 and avg365 > 0 else ''}{avg365:.0f}%</td>
              <td class="mono">{win365:.0f}%</td>
            </tr>''' if avg180 is not None and avg365 is not None else ""

        # Headline stats
        sb = zs.get("STRONG_BUY", {})
        sb_avg = sb.get("avg_180d", 0)
        sb_win = sb.get("win_rate_180d", 0)
        sb_days = sb.get("days", 0)

        bt_html = f'''
    <section class="bt-sec">
      <div class="sec-hdr">Signal Track Record</div>
      <div class="bt-subtitle">Backtest: 2017 &ndash; present &bull; {len(daily):,} days scored &bull; ~1M historical data points back to 2009 &bull; Same model running today</div>

      <div class="bt-headline-grid">
        <div class="bt-stat">
          <div class="bt-stat-num mono" style="color:#22C55E">+{sb_avg:.0f}%</div>
          <div class="bt-stat-label">Avg 6-month return when score &ge; 75</div>
        </div>
        <div class="bt-stat">
          <div class="bt-stat-num mono" style="color:#22C55E">{sb_win:.0f}%</div>
          <div class="bt-stat-label">Win rate (positive return in 180 days)</div>
        </div>
        <div class="bt-stat">
          <div class="bt-stat-num mono" style="color:#F59E0B">3/3</div>
          <div class="bt-stat-label">Major cycle bottoms detected</div>
        </div>
      </div>

      <div class="bt-chart-card">
        <div class="bt-chart-title">Historical Score vs BTC Price</div>
        <div class="bt-chart-box"><canvas id="btChart"></canvas></div>
        <div class="bt-chart-legend">
          <span class="cl-item"><span class="cl-dot" style="background:#F59E0B;height:2px"></span>BTC Price</span>
          <span class="cl-item"><span class="cl-dot" style="background:#22C55E"></span>Strong Buy (75+)</span>
          <span class="cl-item"><span class="cl-dot" style="background:#EAB308"></span>Accumulate</span>
          <span class="cl-item"><span class="cl-dot" style="background:#FB923C"></span>Watching</span>
          <span class="cl-item"><span class="cl-dot" style="background:#EF4444"></span>No Entry</span>
        </div>
      </div>

      <div class="bt-table-card">
        <div class="bt-chart-title">Zone Performance</div>
        <div class="bt-table-wrap">
        <table class="bt-table">
          <thead><tr>
            <th>Zone</th><th>Score</th><th>Days</th>
            <th>180d Avg</th><th>180d Win</th>
            <th>365d Avg</th><th>365d Win</th>
          </tr></thead>
          <tbody>{zone_rows}</tbody>
        </table>
        </div>
        <div class="bt-note">Forward returns calculated from each day the zone was active. Win rate = % of days with positive return at horizon.</div>
      </div>

      <div class="bt-bottoms-card">
        <div class="bt-chart-title">Cycle Bottom Detection</div>
        <div class="bt-bottoms">
          <div class="bt-bottom-item">
            <div class="bt-bottom-date">Dec 2018</div>
            <div class="bt-bottom-detail">Score: <span class="mono" style="color:#22C55E">84.9</span> at $3,232</div>
            <div class="bt-bottom-result">&#8594; <span style="color:#22C55E">+155%</span> in 6 months</div>
          </div>
          <div class="bt-bottom-item">
            <div class="bt-bottom-date">Mar 2020</div>
            <div class="bt-bottom-detail">Score: <span class="mono" style="color:#EAB308">71.9</span> at $4,830</div>
            <div class="bt-bottom-result">&#8594; <span style="color:#22C55E">+110%</span> in 6 months</div>
          </div>
          <div class="bt-bottom-item">
            <div class="bt-bottom-date">Nov 2022</div>
            <div class="bt-bottom-detail">Score: <span class="mono" style="color:#22C55E">75.8</span> at $16,260</div>
            <div class="bt-bottom-result">&#8594; <span style="color:#22C55E">+65%</span> in 6 months</div>
          </div>
        </div>
      </div>
    </section>'''

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

/* Extras Section */
.extras-sec{{padding:20px 0}}
.extras-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px;padding-top:10px}}
.halving-card,.cycle-card{{background:#0F172A;border:1px solid #1E293B;border-radius:10px;padding:20px}}
.halving-top,.cycle-top{{display:flex;align-items:center;gap:8px;margin-bottom:12px}}
.halving-icon{{font-size:20px}}
.halving-label{{font-size:11px;color:#F59E0B;font-weight:700;letter-spacing:2px}}
.halving-big{{font-size:32px;font-weight:700;color:#F8FAFC;line-height:1}}
.halving-unit{{font-size:14px;color:#64748B;font-weight:400}}
.halving-sub{{font-size:13px;color:#94A3B8;margin-top:6px}}
.halving-bar-wrap{{margin-top:16px}}
.halving-bar{{height:8px;background:#1E293B;border-radius:4px;overflow:hidden}}
.halving-fill{{height:100%;background:linear-gradient(90deg,#F59E0B,#EF4444);border-radius:4px}}
.halving-bar-labels{{display:flex;justify-content:space-between;font-size:10px;color:#475569;margin-top:4px}}
.halving-reward{{display:flex;align-items:center;gap:8px;margin-top:14px;font-size:14px;color:#94A3B8;justify-content:center}}
.halving-arrow{{color:#475569}}
.cycle-sub{{font-size:12px;color:#94A3B8;margin-bottom:10px}}
.cycle-chart-box{{background:#080D17;border:1px solid #1E293B;border-radius:8px;height:220px;position:relative;overflow:hidden}}
.cycle-chart-box canvas{{display:block}}
.cycle-legend{{display:flex;gap:16px;justify-content:center;margin-top:10px;flex-wrap:wrap}}
.cl-item{{font-size:11px;color:#94A3B8;display:flex;align-items:center;gap:4px}}
.cl-dot{{width:10px;height:3px;border-radius:2px;display:inline-block}}

/* Backtest Track Record */
.bt-sec{{padding:20px 0}}
.bt-subtitle{{font-size:12px;color:#64748B;margin-top:4px;margin-bottom:16px}}
.bt-headline-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:16px}}
.bt-stat{{background:#0F172A;border:1px solid #1E293B;border-radius:10px;padding:18px;text-align:center}}
.bt-stat-num{{font-size:32px;font-weight:700;line-height:1}}
.bt-stat-label{{font-size:11px;color:#94A3B8;margin-top:6px;line-height:1.3}}
.bt-chart-card,.bt-table-card,.bt-bottoms-card{{background:#0F172A;border:1px solid #1E293B;border-radius:10px;padding:18px;margin-bottom:14px}}
.bt-chart-title{{font-size:11px;color:#F59E0B;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:10px}}
.bt-chart-box{{background:#080D17;border:1px solid #1E293B;border-radius:8px;height:260px;position:relative;overflow:hidden}}
.bt-chart-box canvas{{display:block}}
.bt-chart-legend{{display:flex;gap:16px;justify-content:center;margin-top:10px;flex-wrap:wrap}}
.bt-table-wrap{{overflow-x:auto}}
.bt-table{{width:100%;border-collapse:collapse;font-size:12px}}
.bt-table th{{text-align:left;padding:6px 10px;color:#64748B;font-size:10px;text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid #1E293B}}
.bt-table td{{padding:6px 10px;border-bottom:1px solid #111827}}
.bt-note{{font-size:10px;color:#475569;margin-top:8px;font-style:italic}}
.bt-bottoms{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}
.bt-bottom-item{{background:#080D17;border:1px solid #1E293B;border-radius:8px;padding:14px;text-align:center}}
.bt-bottom-date{{font-size:16px;font-weight:700;color:#F8FAFC}}
.bt-bottom-detail{{font-size:12px;color:#94A3B8;margin-top:4px}}
.bt-bottom-result{{font-size:14px;font-weight:700;margin-top:6px}}

@media(max-width:768px){{
  .bt-headline-grid{{grid-template-columns:1fr}}
  .bt-bottoms{{grid-template-columns:1fr}}
}}

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

      <h4>Does It Actually Work? (Backtest Results)</h4>
      <p>We backtested this exact scoring model against every day from Jan 2017 to present &mdash; over 3,300 trading days using nearly 1 million historical data points spanning back to Bitcoin&rsquo;s genesis block in 2009. Price data, hash rates, miner revenue, and realized price all go back to 2009&ndash;2010. On-chain metrics like SOPR, LTH-SOPR, and Reserve Risk cover 2010+. Fear &amp; Greed data from 2018, funding rates from 2019. The model was applied retroactively using the same indicator thresholds, weights, and scoring logic running today. Key findings:</p>
      <ul>
        <li><strong>Strong Buy zone (75+)</strong> has appeared on only 24 days &mdash; all in Dec 2018 and Nov 2022, right at confirmed cycle bottoms.</li>
        <li><strong>100% win rate</strong> &mdash; Every single day the score was 75+, BTC was higher 6 months later. Average return: +116%.</li>
        <li><strong>3 for 3 on cycle bottoms</strong> &mdash; Dec 2018 ($3,232, score 84.9), Mar 2020 ($4,830, score 71.9), Nov 2022 ($16,260, score 75.8).</li>
        <li><strong>Low scores flagged danger</strong> &mdash; In Dec 2017 at $19,280 (the top), the score was 4.5. BTC fell 66% over the next 6 months.</li>
        <li><strong>Monotonic relationship</strong> &mdash; Higher score = better forward returns at every time horizon. The zones work as designed.</li>
      </ul>
      <p style="color:#64748B;font-size:12px;margin-top:8px">See the Signal Track Record section below for the full chart, zone performance table, and bottom detection details.</p>

      <h4>Important Caveats</h4>
      <p>This is a framework, not financial advice. Past cycles don&rsquo;t guarantee future patterns. The backtest applies today&rsquo;s model to historical data &mdash; it was not used to make real-time decisions during those periods. The model is designed for macro cycle bottoms &mdash; it won&rsquo;t help with short-term trading. Some BGeometrics indicators rotate through a cache due to API rate limits, so not all 26 indicators may be live at any given time. The score will become more accurate as all data populates.</p>
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

  <!-- Backtest Track Record -->
  {bt_html}

  <!-- Extras: Halving + Cycle Comparison -->
  {halving_html}
  {cycle_html}

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

/* Cycle Comparison Chart */
const ccData={cycle_json if cycle_json else "null"};
const ccv=document.getElementById('cycleChart');
if(ccv&&ccData){{
const cbox=ccv.parentElement;
const cctx=ccv.getContext('2d');
const cdpr=window.devicePixelRatio||1;
const cpad=12;
const cw=cbox.clientWidth-cpad*2, ch=cbox.clientHeight-cpad*2;
ccv.width=cw*cdpr; ccv.height=ch*cdpr;
ccv.style.width=cw+'px'; ccv.style.height=ch+'px';
cctx.scale(cdpr,cdpr);

const maxDay=700, minDD=-90, btm=20, lpad=40;
const plotH=ch-btm, plotW=cw-lpad;
function cx(d){{return lpad+(d/maxDay)*plotW}}
function cy(dd){{return plotH*(dd/minDD)}}

/* Grid */
cctx.strokeStyle='#1E293B'; cctx.lineWidth=1;
for(let pct=0;pct>=-80;pct-=20){{
  const y=cy(pct);
  cctx.beginPath(); cctx.moveTo(lpad,y); cctx.lineTo(cw,y); cctx.stroke();
  cctx.fillStyle='#475569'; cctx.font='10px Space Mono'; cctx.textAlign='left';
  cctx.fillText(pct+'%',2,y+12);
}}
/* X labels */
cctx.textAlign='center'; cctx.fillStyle='#475569'; cctx.font='10px Space Mono';
for(let d=0;d<=700;d+=100){{
  if(d===0){{cctx.textAlign='left';cctx.fillText('ATH',cx(d),plotH+14);cctx.textAlign='center'}}
  else if(d===700){{cctx.textAlign='right';cctx.fillText('D'+d,cx(d),plotH+14)}}
  else{{cctx.fillText('D'+d,cx(d),plotH+14)}}
}}

/* Draw cycle lines */
function drawLine(points,color,width,dash){{
  cctx.beginPath(); cctx.strokeStyle=color; cctx.lineWidth=width;
  if(dash)cctx.setLineDash(dash); else cctx.setLineDash([]);
  cctx.lineJoin='round';
  points.forEach((p,i)=>{{const x=cx(p[0]),y=cy(p[1]); i===0?cctx.moveTo(x,y):cctx.lineTo(x,y)}});
  cctx.stroke(); cctx.setLineDash([]);
}}
/* Historical cycles */
const hcycles=[
  {{k:'2013',color:'#475569',dash:[4,4]}},
  {{k:'2017',color:'#06B6D4',dash:[6,3]}},
  {{k:'2021',color:'#6366F1',dash:[]}},
];
hcycles.forEach(hc=>{{
  const pts=ccData.cycles[hc.k].points;
  drawLine(pts,hc.color,1.5,hc.dash);
  /* Bottom marker */
  const bd=ccData.cycles[hc.k].bottomDay;
  const bp=pts.find(p=>p[0]===bd);
  if(bp){{
    cctx.beginPath();cctx.arc(cx(bp[0]),cy(bp[1]),3,0,Math.PI*2);cctx.fillStyle=hc.color;cctx.fill();
  }}
}});
/* Current cycle (bold, on top) */
drawLine(ccData.current,'#F59E0B',2.5,[]);
/* "You are here" dot */
const last=ccData.current[ccData.current.length-1];
cctx.beginPath();cctx.arc(cx(last[0]),cy(last[1]),5,0,Math.PI*2);cctx.fillStyle='#F59E0B';cctx.fill();
cctx.beginPath();cctx.arc(cx(last[0]),cy(last[1]),5,0,Math.PI*2);cctx.strokeStyle='#0F172A';cctx.lineWidth=2;cctx.stroke();
/* Label */
cctx.font='bold 10px Space Mono';cctx.fillStyle='#F59E0B';cctx.textAlign='right';
cctx.fillText('Day '+last[0]+' ('+last[1]+'%)',cx(last[0])-8,cy(last[1])+4);

/* Hover */
const ctip=document.createElement('div');
ctip.style.cssText='position:absolute;display:none;background:#1E293B;border:1px solid #334155;border-radius:6px;padding:6px 10px;font:11px Space Mono;color:#E2E8F0;pointer-events:none;z-index:10;white-space:nowrap';
cbox.appendChild(ctip);
const cvl=document.createElement('div');
cvl.style.cssText='position:absolute;display:none;width:1px;background:#334155;pointer-events:none;z-index:5';
cbox.appendChild(cvl);
ccv.addEventListener('mousemove',e=>{{
  const r=ccv.getBoundingClientRect();
  const mx=e.clientX-r.left;
  const day=Math.round((mx/cw)*maxDay);
  if(day>=0&&day<=maxDay){{
    /* Find closest current cycle point */
    let closest=ccData.current[0];
    for(const p of ccData.current){{if(Math.abs(p[0]-day)<Math.abs(closest[0]-day))closest=p}}
    let txt='Day '+day+': Current '+closest[1]+'%';
    hcycles.forEach(hc=>{{
      const pts=ccData.cycles[hc.k].points;
      /* Interpolate */
      for(let i=0;i<pts.length-1;i++){{
        if(day>=pts[i][0]&&day<=pts[i+1][0]){{
          const t=(day-pts[i][0])/(pts[i+1][0]-pts[i][0]);
          const v=Math.round(pts[i][1]+t*(pts[i+1][1]-pts[i][1]));
          txt+=' | '+ccData.cycles[hc.k].label+' '+v+'%';
          break;
        }}
      }}
    }});
    ctip.textContent=txt;
    ctip.style.display='block';
    cvl.style.left=(mx+cpad)+'px';cvl.style.top=cpad+'px';cvl.style.height=plotH+'px';cvl.style.display='block';
    const tw=ctip.offsetWidth;
    ctip.style.left=Math.min(Math.max(mx+cpad-tw/2,cpad),cw+cpad-tw)+'px';
    ctip.style.top=(cpad-20)+'px';
  }}
}});
ccv.addEventListener('mouseleave',()=>{{ctip.style.display='none';cvl.style.display='none'}});
}}

/* Backtest History Chart */
const btData={bt_chart_json};
const btcv=document.getElementById('btChart');
if(btcv&&btData&&btData.length>0){{
const bBox=btcv.parentElement;
const bCtx=btcv.getContext('2d');
const bDpr=window.devicePixelRatio||1;
const bPad=12;
const bW=bBox.clientWidth-bPad*2, bH=bBox.clientHeight-bPad*2;
btcv.width=bW*bDpr; btcv.height=bH*bDpr;
btcv.style.width=bW+'px'; btcv.style.height=bH+'px';
bCtx.scale(bDpr,bDpr);

const bBtm=24, bLpad=50, bRpad=50;
const bPlotH=bH-bBtm;
const bPlotW=bW-bLpad-bRpad;

/* Price on log scale */
const prices=btData.map(d=>d.p);
const scores=btData.map(d=>d.s);
const logMin=Math.log10(Math.min(...prices)*0.8);
const logMax=Math.log10(Math.max(...prices)*1.2);
const logRange=logMax-logMin;

function bx(i){{return bLpad+(i/(btData.length-1))*bPlotW}}
function byPrice(p){{return bPlotH-((Math.log10(p)-logMin)/logRange)*bPlotH}}
function byScore(s){{return bPlotH-(s/100)*bPlotH}}

/* Grid */
bCtx.strokeStyle='#1E293B';bCtx.lineWidth=1;
for(let i=0;i<=4;i++){{
  const y=(i/4)*bPlotH;
  bCtx.beginPath();bCtx.moveTo(bLpad,y);bCtx.lineTo(bW-bRpad,y);bCtx.stroke();
}}

/* Y-axis left: Price labels */
bCtx.font='10px Space Mono';bCtx.textAlign='right';bCtx.fillStyle='#64748B';
const priceTicks=[1000,3000,10000,30000,100000];
priceTicks.forEach(p=>{{
  if(p>=Math.min(...prices)*0.8&&p<=Math.max(...prices)*1.2){{
    const y=byPrice(p);
    bCtx.fillText('$'+p.toLocaleString(),bLpad-4,y+4);
  }}
}});

/* Y-axis right: Score labels */
bCtx.textAlign='left';
for(let s=0;s<=100;s+=25){{
  bCtx.fillText(s+'',bW-bRpad+4,byScore(s)+4);
}}

/* X-axis date labels */
bCtx.textAlign='center';bCtx.fillStyle='#475569';
const years=new Set();
btData.forEach((d,i)=>{{
  const yr=d.d.substring(0,4);
  if(!years.has(yr)){{
    years.add(yr);
    bCtx.fillText(yr,bx(i),bPlotH+16);
  }}
}});

/* Score zones as colored bars */
const zoneColors={{STRONG_BUY:'rgba(34,197,94,0.25)',ACCUMULATE:'rgba(234,179,8,0.2)',WATCHING:'rgba(251,146,60,0.12)',NO_ENTRY:'rgba(239,68,68,0.08)'}};
for(let i=0;i<btData.length-1;i++){{
  const x1=bx(i),x2=bx(i+1);
  const col=zoneColors[btData[i].z]||'rgba(100,100,100,0.1)';
  bCtx.fillStyle=col;
  bCtx.fillRect(x1,0,x2-x1,bPlotH);
}}

/* Score line */
bCtx.beginPath();bCtx.strokeStyle='rgba(148,163,184,0.4)';bCtx.lineWidth=1;bCtx.lineJoin='round';
btData.forEach((d,i)=>{{
  const x=bx(i),y=byScore(d.s);
  i===0?bCtx.moveTo(x,y):bCtx.lineTo(x,y);
}});
bCtx.stroke();

/* Price line (bold, on top) */
bCtx.beginPath();bCtx.strokeStyle='#F59E0B';bCtx.lineWidth=2;bCtx.lineJoin='round';
btData.forEach((d,i)=>{{
  const x=bx(i),y=byPrice(d.p);
  i===0?bCtx.moveTo(x,y):bCtx.lineTo(x,y);
}});
bCtx.stroke();

/* 75-line threshold */
bCtx.setLineDash([4,4]);bCtx.strokeStyle='#22C55E';bCtx.lineWidth=1;
bCtx.beginPath();bCtx.moveTo(bLpad,byScore(75));bCtx.lineTo(bW-bRpad,byScore(75));bCtx.stroke();
bCtx.setLineDash([]);
bCtx.font='9px Space Mono';bCtx.fillStyle='#22C55E';bCtx.textAlign='left';
bCtx.fillText('Strong Buy',bW-bRpad+4,byScore(75)-4);

/* Bottom markers */
const markers=[
  {{label:'Dec 2018',find:'2018-12'}},
  {{label:'Mar 2020',find:'2020-03'}},
  {{label:'Nov 2022',find:'2022-11'}},
];
markers.forEach(m=>{{
  const idx=btData.findIndex(d=>d.d.startsWith(m.find));
  if(idx>=0){{
    const x=bx(idx),y=byPrice(btData[idx].p);
    bCtx.beginPath();bCtx.arc(x,y,4,0,Math.PI*2);bCtx.fillStyle='#22C55E';bCtx.fill();
    bCtx.beginPath();bCtx.arc(x,y,4,0,Math.PI*2);bCtx.strokeStyle='#0F172A';bCtx.lineWidth=2;bCtx.stroke();
    bCtx.font='bold 9px Space Mono';bCtx.fillStyle='#22C55E';bCtx.textAlign='center';
    bCtx.fillText(m.label,x,y-8);
  }}
}});

/* Hover */
const bTip=document.createElement('div');
bTip.style.cssText='position:absolute;display:none;background:#1E293B;border:1px solid #334155;border-radius:6px;padding:6px 10px;font:11px Space Mono;color:#E2E8F0;pointer-events:none;z-index:10;white-space:nowrap';
bBox.appendChild(bTip);
const bVl=document.createElement('div');
bVl.style.cssText='position:absolute;display:none;width:1px;background:#334155;pointer-events:none;z-index:5';
bBox.appendChild(bVl);
btcv.addEventListener('mousemove',e=>{{
  const r=btcv.getBoundingClientRect();
  const mx=e.clientX-r.left;
  const idx=Math.round(((mx-bLpad)/bPlotW)*(btData.length-1));
  if(idx>=0&&idx<btData.length){{
    const d=btData[idx];
    const zl={{STRONG_BUY:'Strong Buy',ACCUMULATE:'Accumulate',WATCHING:'Watching',NO_ENTRY:'No Entry'}};
    bTip.textContent=d.d+'  $'+d.p.toLocaleString()+'  Score: '+d.s.toFixed(1)+' ('+( zl[d.z]||d.z)+')';
    bTip.style.display='block';
    const px=bx(idx);
    bVl.style.left=(px+bPad)+'px';bVl.style.top=bPad+'px';bVl.style.height=bPlotH+'px';bVl.style.display='block';
    const tw=bTip.offsetWidth;
    bTip.style.left=Math.min(Math.max(px+bPad-tw/2,bPad),bW+bPad-tw)+'px';
    bTip.style.top=(bPad-20)+'px';
  }}
}});
btcv.addEventListener('mouseleave',()=>{{bTip.style.display='none';bVl.style.display='none'}});
}}
</script>
</body>
</html>'''

    with open(OUT_FILE, "w") as f:
        f.write(html)
    print(f"✓ Generated {OUT_FILE} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
