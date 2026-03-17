#!/usr/bin/env python3
"""
Bitcoin Re-Entry Signal — Backtester

Replays the composite scoring model against historical data to answer:
"When the score was high, what actually happened to BTC price?"

Reads from data/history/ (populated by download-history.py).
Outputs data/backtest_results.json with daily scores + forward returns.
"""

import json, math, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

DATA_DIR = Path(__file__).parent.parent / "data"
HIST_DIR = DATA_DIR / "history"
OUT_FILE = DATA_DIR / "backtest_results.json"

# ─── Data Loading ──────────────────────────────────────

def load_hist(filename):
    """Load a history file, return as {date: value} dict."""
    path = HIST_DIR / f"{filename}.json"
    if not path.exists():
        return {}
    data = json.load(open(path))
    if not isinstance(data, list):
        return {}
    result = {}
    for item in data:
        date = item.get("date", "")
        val = item.get("value")
        if date and val is not None:
            result[date] = val
    return result


def load_funding_rates():
    """Load funding rates, aggregate to daily average."""
    path = HIST_DIR / "bn_funding_rates.json"
    if not path.exists():
        return {}
    data = json.load(open(path))
    daily = defaultdict(list)
    for item in data:
        daily[item["date"]].append(item["rate"])
    return {d: sum(rates)/len(rates) for d, rates in daily.items()}


# ─── Scoring Functions (mirror of fetch-data.py) ─────

def score_val(val, ranges):
    if val is None:
        return None
    for threshold, score in ranges:
        if val <= threshold:
            return score
    return ranges[-1][1] if ranges else 0


def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def compute_score_for_day(date_str, price, prices_up_to, indicators):
    """
    Compute the composite score for a given day using available data.
    indicators = dict of {metric_name: value} for this date.
    prices_up_to = list of daily prices ending on this date.
    """

    # ── Domain 1: On-Chain Valuation (30%) ──
    d1 = []

    v = indicators.get("mvrv_zscore")
    if v is not None:
        s = score_val(v, [(-1.5, 10), (-1, 9), (-0.5, 8), (0, 7), (0.5, 5), (1, 3), (2, 1), (999, 0)])
        d1.append(("MVRV-Z Score", s, 2.5))

    v = indicators.get("nupl")
    if v is not None:
        s = score_val(v, [(-0.2, 10), (0, 8), (0.1, 6), (0.2, 5), (0.3, 3), (0.5, 1), (999, 0)])
        d1.append(("NUPL", s, 2))

    v = indicators.get("realized_price")
    if v is not None and price > 0:
        ratio = price / v
        s = score_val(ratio, [(0.75, 10), (0.85, 9), (1.0, 8), (1.1, 6), (1.2, 4), (1.3, 2), (999, 0)])
        d1.append(("Realized Price", s, 2))

    v = indicators.get("supply_profit")
    if v is not None:
        supply_pct = (v / 19_800_000) * 100  # approximate
        s = score_val(supply_pct, [(45, 10), (50, 9), (55, 7), (60, 5), (70, 3), (80, 1), (999, 0)])
        d1.append(("Supply in Profit", s, 2))

    v = indicators.get("reserve_risk")
    if v is not None:
        s = score_val(v, [(0.0005, 10), (0.001, 9), (0.002, 7), (0.005, 4), (0.01, 2), (999, 0)])
        d1.append(("Reserve Risk", s, 2))

    v = indicators.get("ssr")
    if v is not None:
        s = score_val(v, [(3, 10), (5, 8), (7, 6), (10, 4), (15, 2), (999, 0)])
        d1.append(("Stablecoin Ratio", s, 1.5))

    v = indicators.get("thermocap")
    if v is not None:
        s = score_val(v, [(4, 10), (6, 8), (8, 6), (12, 3), (999, 0)])
        d1.append(("Thermocap", s, 1))

    # ── Domain 2: Miner Health (15%) ──
    d2 = []

    # Hash Ribbon — need rolling price array with hash rates
    hr_data = indicators.get("_hash_rates")  # list of recent hash rates
    if hr_data and len(hr_data) >= 60:
        hr_30d = sma(hr_data, 30)
        hr_60d = sma(hr_data, 60)
        if hr_30d and hr_60d:
            if hr_30d < hr_60d:
                s = 7  # CAPITULATION
            else:
                # Check if just crossed
                prev_30 = sma(hr_data[:-1], 30)
                prev_60 = sma(hr_data[:-1], 60)
                if prev_30 and prev_60 and prev_30 < prev_60:
                    s = 10  # BUY SIGNAL
                else:
                    s = 4  # RECOVERY
            d2.append(("Hash Ribbon", s, 2))

    # Puell Multiple
    mr_data = indicators.get("_miner_revenues")  # list of recent revenues
    if mr_data and len(mr_data) >= 365:
        avg_365 = sma(mr_data, 365)
        if avg_365 and avg_365 > 0:
            puell = mr_data[-1] / avg_365
            s = score_val(puell, [(0.3, 10), (0.5, 8), (0.7, 5), (1.0, 3), (1.5, 1), (999, 0)])
            d2.append(("Puell Multiple", s, 1.5))

    # ── Domain 3: Technical / Price (20%) ──
    d3 = []

    if len(prices_up_to) >= 200:
        sma200d = sma(prices_up_to, 200)
        if sma200d:
            mayer = price / sma200d
            s = score_val(mayer, [(0.5, 10), (0.6, 9), (0.7, 7), (0.8, 6), (0.9, 4), (1.0, 2), (999, 0)])
            d3.append(("Mayer Multiple", s, 2))

    weekly = prices_up_to[::7]
    if len(weekly) >= 200:
        wma200 = sma(weekly, 200)
        if wma200:
            ratio = price / wma200
            s = score_val(ratio, [(0.9, 10), (1.0, 9), (1.1, 7), (1.15, 5), (1.3, 3), (1.5, 1), (999, 0)])
            d3.append(("200-Week MA", s, 2))

    # Pi Cycle Bottom
    if len(prices_up_to) >= 471:
        ema150 = ema(prices_up_to, 150)
        sma471 = sma(prices_up_to, 471)
        if ema150 and sma471:
            pi_line = sma471 * 0.475
            s = 10 if ema150 < pi_line else 1
            d3.append(("Pi Cycle Bottom", s, 1.5))

    # Drawdown from ATH
    ath = max(prices_up_to) if prices_up_to else price
    dd = abs(((price - ath) / ath) * 100) if ath > 0 else 0
    s = score_val(dd, [(25, 0), (35, 2), (45, 4), (55, 6), (65, 7), (75, 9), (999, 10)])
    d3.append(("Drawdown Depth", s, 1))

    # Rainbow Chart
    genesis_ts = datetime(2009, 1, 9, tzinfo=timezone.utc).timestamp() * 1000
    current_ts = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000
    days_since_genesis = (current_ts - genesis_ts) / (1000 * 60 * 60 * 24)
    if days_since_genesis > 0:
        rainbow_center = 10 ** (-17.31 + 5.82 * math.log10(days_since_genesis))
        bands = {
            "Fire Sale": rainbow_center * 0.32, "BUY!": rainbow_center * 0.52,
            "Accumulate": rainbow_center * 0.82, "Still Cheap": rainbow_center * 1.25,
            "HODL!": rainbow_center * 1.85,
        }
        band_scores = {"Fire Sale": 10, "BUY!": 8, "Accumulate": 6, "Still Cheap": 3, "HODL!": 1}
        current_band = "HODL!"
        for bname in ["Fire Sale", "BUY!", "Accumulate", "Still Cheap"]:
            if price <= bands.get(bname, 0) * (1.25 / 0.32):  # next band threshold
                current_band = bname
                break
        # More precise: check each band boundary
        band_names = list(bands.keys())
        current_band = "HODL!"
        for i, bname in enumerate(band_names):
            if i + 1 < len(band_names):
                if price <= bands[band_names[i + 1]]:
                    current_band = bname
                    break
            else:
                if price <= bands[bname] * 2:
                    current_band = bname
                    break
        rs = band_scores.get(current_band, 0)
        d3.append(("Rainbow Chart", rs, 1))

    # ── Domain 4: Sentiment & Positioning (15%) ──
    d4 = []

    v = indicators.get("sopr")
    if v is not None:
        s = score_val(v, [(0.90, 10), (0.95, 8), (0.98, 6), (1.00, 5), (1.02, 3), (999, 0)])
        d4.append(("SOPR", s, 2))

    v = indicators.get("lth_sopr")
    if v is not None:
        s = score_val(v, [(0.90, 10), (0.95, 9), (1.00, 7), (1.05, 4), (1.2, 2), (999, 0)])
        d4.append(("LTH-SOPR", s, 1.5))

    v = indicators.get("fear_greed")
    if v is not None:
        s = score_val(v, [(10, 10), (15, 9), (20, 8), (25, 7), (35, 4), (50, 2), (999, 0)])
        d4.append(("Fear & Greed", s, 1.5))

    # Fear duration (consecutive days of extreme fear)
    ef_days = indicators.get("_fear_streak", 0)
    s = score_val(-ef_days, [(-30, 10), (-21, 8), (-14, 6), (-7, 4), (-3, 2), (999, 0)])
    d4.append(("Fear Duration", s, 1))

    # Funding rates
    v = indicators.get("funding_rate")
    if v is not None:
        s = score_val(v, [(-0.01, 10), (-0.005, 8), (-0.001, 6), (0, 4), (0.005, 1), (999, 0)])
        d4.append(("Funding Rates", s, 1))

    # ── Domain 5: Exchange & Liquidity (10%) ──
    d5 = []

    v = indicators.get("exchange_netflow")
    if v is not None:
        s = 8 if v < -500 else 6 if v < -100 else 4 if v < 0 else 2 if v < 500 else 0
        d5.append(("Exchange Netflow", s, 2))

    v = indicators.get("nvts")
    if v is not None:
        s = score_val(v, [(30, 10), (45, 9), (60, 7), (80, 5), (100, 3), (150, 1), (999, 0)])
        d5.append(("NVT Signal", s, 1.5))

    # ── Domain 6: Cycle Timing (10%) ──
    d6 = []

    # Cycle progress (days since ATH / ~383)
    if ath > 0 and prices_up_to:
        ath_idx = len(prices_up_to) - 1
        for i in range(len(prices_up_to) - 1, -1, -1):
            if prices_up_to[i] == ath:
                ath_idx = i
                break
        days_since_ath = len(prices_up_to) - 1 - ath_idx
        cp = min(days_since_ath / 383, 1.0)
        s = score_val(cp, [(0.2, 0), (0.3, 2), (0.4, 3), (0.55, 4), (0.7, 6), (0.85, 8), (0.95, 9), (999, 10)])
        d6.append(("Cycle Progress", s, 2))

    v = indicators.get("rhodl_ratio")
    if v is not None:
        s = score_val(v, [(300, 10), (500, 8), (1000, 5), (2000, 3), (5000, 1), (999, 0)])
        d6.append(("RHODL Ratio", s, 1.5))

    # ── Aggregate ──
    def domain_avg(items):
        if not items:
            return 0, 0
        tw = sum(w for _, _, w in items)
        ts = sum(s * w for _, s, w in items)
        return round(ts / tw, 1) if tw > 0 else 0, len(items)

    domains_raw = [
        ("onChain",   0.30, d1),
        ("miner",     0.15, d2),
        ("technical", 0.20, d3),
        ("sentiment", 0.15, d4),
        ("exchange",  0.10, d5),
        ("cycle",     0.10, d6),
    ]

    domains = {}
    for key, weight, items in domains_raw:
        score, count = domain_avg(items)
        domains[key] = {"score": score, "weight": weight, "count": count}

    # Redistribute weight from empty domains
    active_weight = sum(d["weight"] for d in domains.values() if d["count"] > 0)
    scale = 1.0 / active_weight if active_weight > 0 else 1.0

    composite = 0
    for d in domains.values():
        if d["count"] > 0:
            ew = d["weight"] * scale
            composite += d["score"] * ew * 10

    composite = round(composite, 1)

    if composite >= 75:   zone = "STRONG_BUY"
    elif composite >= 50: zone = "ACCUMULATE"
    elif composite >= 25: zone = "WATCHING"
    else:                 zone = "NO_ENTRY"

    return {
        "score": composite,
        "zone": zone,
        "domains": {k: {"score": v["score"], "count": v["count"]} for k, v in domains.items()},
        "indicators_available": sum(d["count"] for d in domains.values()),
    }


# ─── Main Backtest Loop ──────────────────────────────

def run_backtest():
    print("Bitcoin Re-Entry Signal — Backtester")
    print("=" * 50)

    # Load all historical data
    print("\n📂 Loading historical data...")

    prices_hist = load_hist("bc_price")
    hash_rates_hist = load_hist("bc_hash_rate")
    miner_rev_hist = load_hist("bc_miner_revenue")
    fear_greed_hist = load_hist("fg_fear_greed")
    funding_hist = load_funding_rates()

    bg_data = {
        "mvrv_zscore": load_hist("bg_mvrv_zscore"),
        "nupl": load_hist("bg_nupl"),
        "sopr": load_hist("bg_sopr"),
        "realized_price": load_hist("bg_realized_price"),
        "reserve_risk": load_hist("bg_reserve_risk"),
        "supply_profit": load_hist("bg_supply_profit"),
        "lth_sopr": load_hist("bg_lth_sopr"),
        "sth_sopr": load_hist("bg_sth_sopr"),
        "ssr": load_hist("bg_ssr"),
        "rhodl_ratio": load_hist("bg_rhodl_ratio"),
        "nvts": load_hist("bg_nvts"),
        "thermocap": load_hist("bg_thermocap"),
        "exchange_reserve": load_hist("bg_exchange_reserve"),
        "exchange_netflow": load_hist("bg_exchange_netflow"),
    }

    # Report data availability
    for name, data in bg_data.items():
        if data:
            dates = sorted(data.keys())
            print(f"  ✓ {name:25s} {len(data):>5} days  ({dates[0]} → {dates[-1]})")
        else:
            print(f"  ✗ {name:25s} MISSING")

    print(f"  ✓ {'price':25s} {len(prices_hist):>5} days")
    print(f"  ✓ {'hash_rate':25s} {len(hash_rates_hist):>5} days")
    print(f"  ✓ {'miner_revenue':25s} {len(miner_rev_hist):>5} days")
    print(f"  ✓ {'fear_greed':25s} {len(fear_greed_hist):>5} days")
    print(f"  ✓ {'funding_rates':25s} {len(funding_hist):>5} days")

    if not prices_hist:
        print("\n✗ No price data. Run download-history.py first.")
        sys.exit(1)

    # Build sorted date list
    all_dates = sorted(prices_hist.keys())
    # Start from 2017-01-01 (need ~2 years of price history for 200-week MA)
    start_date = "2017-01-01"
    test_dates = [d for d in all_dates if d >= start_date]

    print(f"\n📊 Running backtest: {test_dates[0]} → {test_dates[-1]} ({len(test_dates)} days)")

    # Pre-build price array for rolling window
    price_dates = sorted(prices_hist.keys())
    price_values = [prices_hist[d] for d in price_dates]
    date_to_price_idx = {d: i for i, d in enumerate(price_dates)}

    # Pre-build hash rate and miner revenue arrays
    hr_dates = sorted(hash_rates_hist.keys())
    hr_values = [hash_rates_hist[d] for d in hr_dates]
    date_to_hr_idx = {d: i for i, d in enumerate(hr_dates)}

    mr_dates = sorted(miner_rev_hist.keys())
    mr_values = [miner_rev_hist[d] for d in mr_dates]
    date_to_mr_idx = {d: i for i, d in enumerate(mr_dates)}

    # Pre-compute fear streak for each date
    fg_dates = sorted(fear_greed_hist.keys())
    fear_streaks = {}
    streak = 0
    for d in fg_dates:
        if fear_greed_hist[d] < 25:
            streak += 1
        else:
            streak = 0
        fear_streaks[d] = streak

    # Run backtest
    results = []
    for i, date in enumerate(test_dates):
        price = prices_hist[date]
        if price <= 0:
            continue

        # Build price window
        pidx = date_to_price_idx.get(date)
        if pidx is None:
            continue
        prices_window = price_values[:pidx + 1]

        # Build indicators dict
        indicators = {}
        for key, data in bg_data.items():
            if date in data:
                indicators[key] = data[date]

        # Hash rate window
        hr_idx = date_to_hr_idx.get(date)
        if hr_idx is not None and hr_idx >= 60:
            indicators["_hash_rates"] = hr_values[:hr_idx + 1]

        # Miner revenue window
        mr_idx = date_to_mr_idx.get(date)
        if mr_idx is not None and mr_idx >= 365:
            indicators["_miner_revenues"] = mr_values[:mr_idx + 1]

        # Fear & Greed
        if date in fear_greed_hist:
            indicators["fear_greed"] = fear_greed_hist[date]
            indicators["_fear_streak"] = fear_streaks.get(date, 0)

        # Funding rates (use 30-day average)
        if date in funding_hist:
            # Get last 30 days of funding
            dt = datetime.strptime(date, "%Y-%m-%d")
            rates_30d = []
            for dd in range(30):
                dstr = (dt - timedelta(days=dd)).strftime("%Y-%m-%d")
                if dstr in funding_hist:
                    rates_30d.append(funding_hist[dstr])
            if rates_30d:
                indicators["funding_rate"] = sum(rates_30d) / len(rates_30d)

        # Compute score
        result = compute_score_for_day(date, price, prices_window, indicators)
        result["date"] = date
        result["price"] = round(price, 2)
        results.append(result)

        if i % 365 == 0:
            print(f"  {date}: score={result['score']:.1f} zone={result['zone']} price=${price:,.0f} ({result['indicators_available']} indicators)")

    print(f"\n  Computed {len(results)} daily scores")

    # ── Forward Returns Analysis ──
    print("\n📈 Computing forward returns...")

    price_lookup = prices_hist
    for r in results:
        dt = datetime.strptime(r["date"], "%Y-%m-%d")
        for days_fwd in [30, 90, 180, 365]:
            fwd_date = (dt + timedelta(days=days_fwd)).strftime("%Y-%m-%d")
            fwd_price = price_lookup.get(fwd_date)
            if fwd_price:
                r[f"return_{days_fwd}d"] = round(((fwd_price - r["price"]) / r["price"]) * 100, 1)
            else:
                r[f"return_{days_fwd}d"] = None

    # ── Zone Statistics ──
    print("\n═══ RESULTS ═══\n")

    zones = ["STRONG_BUY", "ACCUMULATE", "WATCHING", "NO_ENTRY"]
    zone_names = {"STRONG_BUY": "Strong Buy (75-100)", "ACCUMULATE": "Accumulate (50-75)",
                  "WATCHING": "Watching (25-50)", "NO_ENTRY": "No Entry (0-25)"}

    for zone in zones:
        zone_days = [r for r in results if r["zone"] == zone]
        if not zone_days:
            print(f"  {zone_names[zone]}: 0 days")
            continue

        print(f"  {zone_names[zone]}: {len(zone_days)} days")
        for period in [30, 90, 180, 365]:
            key = f"return_{period}d"
            returns = [r[key] for r in zone_days if r[key] is not None]
            if returns:
                avg = sum(returns) / len(returns)
                med = sorted(returns)[len(returns) // 2]
                pos = sum(1 for r in returns if r > 0) / len(returns) * 100
                mn = min(returns)
                mx = max(returns)
                print(f"    {period:>3}d: avg={avg:>+7.1f}%  med={med:>+7.1f}%  win={pos:.0f}%  range=[{mn:+.1f}%, {mx:+.1f}%]  (n={len(returns)})")
        print()

    # ── Score Bucket Analysis ──
    print("  Score Buckets (10-point increments):")
    for lo in range(0, 100, 10):
        hi = lo + 10
        bucket = [r for r in results if lo <= r["score"] < hi]
        if not bucket:
            continue
        returns_180 = [r["return_180d"] for r in bucket if r.get("return_180d") is not None]
        if returns_180:
            avg = sum(returns_180) / len(returns_180)
            pos = sum(1 for r in returns_180 if r > 0) / len(returns_180) * 100
            print(f"    {lo:>2}-{hi:<2}: {len(bucket):>4} days  180d avg={avg:>+7.1f}%  win={pos:.0f}%")

    # ── Key Moments ──
    print("\n  Highest Score Days:")
    top_days = sorted(results, key=lambda r: r["score"], reverse=True)[:10]
    for r in top_days:
        fwd = r.get("return_180d")
        fwd_str = f"  180d: {fwd:+.1f}%" if fwd is not None else ""
        print(f"    {r['date']}  score={r['score']:5.1f}  ${r['price']:>10,.0f}{fwd_str}")

    print("\n  Lowest Score Days:")
    bottom_days = sorted(results, key=lambda r: r["score"])[:10]
    for r in bottom_days:
        fwd = r.get("return_180d")
        fwd_str = f"  180d: {fwd:+.1f}%" if fwd is not None else ""
        print(f"    {r['date']}  score={r['score']:5.1f}  ${r['price']:>10,.0f}{fwd_str}")

    # ── Known Cycle Bottoms — Did we catch them? ──
    print("\n  Known Cycle Bottoms — Signal Check:")
    bottoms = [
        ("2018-12-15", "2018 Bear Bottom (~$3,200)"),
        ("2020-03-13", "COVID Crash ($3,800)"),
        ("2022-11-21", "FTX Crash Bottom (~$15,500)"),
    ]
    for bdate, label in bottoms:
        # Find closest date in results
        closest = min(results, key=lambda r: abs((datetime.strptime(r["date"], "%Y-%m-%d") - datetime.strptime(bdate, "%Y-%m-%d")).days))
        # Also check ±30 days for peak score
        dt = datetime.strptime(bdate, "%Y-%m-%d")
        window = [r for r in results if abs((datetime.strptime(r["date"], "%Y-%m-%d") - dt).days) <= 30]
        peak = max(window, key=lambda r: r["score"]) if window else closest
        print(f"    {label}:")
        print(f"      On {closest['date']}: score={closest['score']:.1f} ({closest['zone']}), price=${closest['price']:,.0f}")
        if peak["date"] != closest["date"]:
            print(f"      Peak nearby: {peak['date']}: score={peak['score']:.1f} ({peak['zone']})")
        fwd = closest.get("return_180d")
        if fwd is not None:
            print(f"      180d return: {fwd:+.1f}%")

    # Save results
    save_data = {
        "meta": {
            "start_date": results[0]["date"],
            "end_date": results[-1]["date"],
            "total_days": len(results),
            "computed_at": datetime.now(tz=timezone.utc).isoformat(),
        },
        "daily": results,
        "zone_stats": {},
    }

    for zone in zones:
        zone_days = [r for r in results if r["zone"] == zone]
        stats = {"days": len(zone_days)}
        for period in [30, 90, 180, 365]:
            key = f"return_{period}d"
            returns = [r[key] for r in zone_days if r[key] is not None]
            if returns:
                stats[f"avg_{period}d"] = round(sum(returns) / len(returns), 1)
                stats[f"median_{period}d"] = round(sorted(returns)[len(returns) // 2], 1)
                stats[f"win_rate_{period}d"] = round(sum(1 for r in returns if r > 0) / len(returns) * 100, 1)
                stats[f"min_{period}d"] = round(min(returns), 1)
                stats[f"max_{period}d"] = round(max(returns), 1)
        save_data["zone_stats"][zone] = stats

    with open(OUT_FILE, "w") as f:
        json.dump(save_data, f, indent=2)
    print(f"\n✓ Results saved to {OUT_FILE}")


if __name__ == "__main__":
    run_backtest()
