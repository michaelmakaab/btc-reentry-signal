#!/usr/bin/env python3
"""
Bitcoin Re-Entry Signal v2 — Data Engine

Data sources:
  - BGeometrics (bitcoin-data.com): On-chain metrics (8 calls/hr free, cached)
  - Blockchain.info: Price history, hash rate, miner revenue
  - Alternative.me: Fear & Greed Index
  - Binance: Funding rates

Smart caching: BGeometrics values cached for 6 hours. Priority queue
ensures the most critical indicators get refreshed first.
"""

import json, math, os, sys, time
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_FILE = DATA_DIR / "bg_cache.json"

# ─── Helpers ────────────────────────────────────────────

class RateLimited(Exception):
    """Raised when an API returns 429 Too Many Requests."""
    pass

def fetch_json(url, label, timeout=30):
    try:
        req = Request(url, headers={"User-Agent": "BTC-ReEntry/2.0", "Accept": "application/json"})
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            if not raw.strip():
                print(f"  ✗ {label}: empty response (HTTP {resp.status})")
                return None
            data = json.loads(raw)
        # Debug: log full response for endpoints that have been failing
        if label in ("realized_price", "lth_sopr", "rhodl_ratio", "sth_sopr", "exchange_netflow"):
            print(f"  ✓ {label}: {json.dumps(data)}")
        else:
            print(f"  ✓ {label}")
        return data
    except json.JSONDecodeError as e:
        print(f"  ✗ {label}: bad JSON — {str(e)[:60]}")
        print(f"    ↳ raw response: {raw[:200] if raw else '(empty)'}")
        return None
    except Exception as e:
        msg = str(e)
        if "429" in msg or "Rate limit" in msg or "Too Many" in msg:
            print(f"  ⏳ {label}: rate limited (using cache)")
            raise RateLimited(label)
        else:
            print(f"  ✗ {label}: {msg}")
        return None

def sma(arr, period):
    if len(arr) < period: return None
    return sum(arr[-period:]) / period

def ema(arr, period):
    if len(arr) < period: return None
    k = 2 / (period + 1)
    e = sum(arr[:period]) / period
    for v in arr[period:]:
        e = v * k + e * (1 - k)
    return e

def r(val, decimals=2):
    return round(val, decimals) if val is not None else None


# ─── BGeometrics Smart Cache ───────────────────────────

# Priority order: most critical for bottom detection first
BG_ENDPOINTS = [
    # Priority 1: Core on-chain (replace all manual data)
    ("mvrv_zscore",      "/v1/mvrv-zscore/1",       "mvrvZscore"),
    ("nupl",             "/v1/nupl/1",               "nupl"),
    ("sopr",             "/v1/sopr/1",               "sopr"),
    ("reserve_risk",     "/v1/reserve-risk/1",       "reserveRisk"),
    ("realized_price",   "/v1/realized-price/1",     "realizedPrice"),
    ("supply_profit",    "/v1/supply-profit/1",      "supplyProfit"),
    ("lth_sopr",         "/v1/lth-sopr/1",           "lthSopr"),
    ("ssr",              "/v1/ssr/1",                 "ssrStablecoin"),
    # Priority 2: Additional indicators
    ("exchange_reserve", "/v1/exchange-reserve-btc/1","exchangeReserveBtc"),
    ("rhodl_ratio",      "/v1/rhodl-ratio/1",        "rhodlRatio1m"),
    ("nvts",             "/v1/nvts/1",               "nvts"),
    ("thermocap_mult",   "/v1/thermocap-multiple/1", "thermocapMultiple"),
    ("sth_sopr",         "/v1/sth-sopr/1",           "sthSopr"),
    ("exchange_netflow", "/v1/exchange-netflow-btc/1","exchangeNetflowBtc"),
    # Removed: open_interest (now from Binance), nupl_zone (redundant, we compute from nupl)
]

CACHE_MAX_AGE = 20 * 3600  # 20 hours (data is daily resolution)
BG_MAX_CALLS = 8  # Match 8/hr free tier limit

def load_cache():
    if CACHE_FILE.exists():
        return json.load(open(CACHE_FILE))
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)

def fetch_bgeometrics():
    """Fetch BGeometrics data with smart caching and rate limit awareness.

    Strategy: Prioritize endpoints that have NEVER been cached (no data at all)
    over refreshing already-cached values. This ensures all domains eventually
    get data instead of the same Priority 1 endpoints hogging every run.
    """
    print("\n🔗 Fetching BGeometrics on-chain data...")
    cache = load_cache()
    now = time.time()
    calls_made = 0

    # Split endpoints into: never cached (urgent), stale (need refresh), fresh (skip)
    never_cached = []
    never_cached_failing = []  # Never cached AND has consecutive failures
    stale = []
    fresh = []

    for key, path, field in BG_ENDPOINTS:
        cached = cache.get(key)
        if not cached or cached.get("value") is None:
            fails = cache.get(key, {}).get("consecutive_failures", 0)
            if fails >= 3:
                never_cached_failing.append((key, path, field))
            else:
                never_cached.append((key, path, field))
        elif (now - cached.get("fetched_at", 0)) >= CACHE_MAX_AGE:
            stale.append((key, path, field))
        else:
            fresh.append((key, path, field))

    # Log fresh (skipped) endpoints
    for key, path, field in fresh:
        print(f"  ● {key}: cached ({cache[key].get('value')})")

    # Fetch order: never-cached first, then stale, then chronically failing (low priority)
    fetch_queue = never_cached + stale + never_cached_failing
    if never_cached:
        print(f"  → {len(never_cached)} endpoints never cached — fetching first")
    if never_cached_failing:
        print(f"  → {len(never_cached_failing)} endpoints failing repeatedly — deprioritized")

    rate_limited = False
    for key, path, field in fetch_queue:
        # Rate limit check (our own budget)
        if calls_made >= BG_MAX_CALLS:
            if cache.get(key) and cache[key].get("value") is not None:
                print(f"  ⏸ {key}: budget used (stale cache available)")
            else:
                print(f"  ⏸ {key}: budget used (will fetch next run)")
            continue

        # If API already rate-limited us, don't bother trying more
        if rate_limited:
            if not (cache.get(key) and cache[key].get("value") is not None):
                print(f"  ⏸ {key}: API rate limited (will fetch next run)")
            continue

        # Fetch
        try:
            data = fetch_json(f"https://bitcoin-data.com{path}", key)
        except RateLimited:
            rate_limited = True
            # Track failure but don't count against budget
            prev = cache.get(key, {})
            cache[key] = {**prev, "consecutive_failures": prev.get("consecutive_failures", 0) + 1}
            continue

        if data and field in data:
            val = data[field]
            # Parse numeric strings
            try: val = float(val)
            except (ValueError, TypeError): pass
            cache[key] = {
                "value": val,
                "date": data.get("d", ""),
                "fetched_at": now,
                "consecutive_failures": 0
            }
            calls_made += 1
            time.sleep(0.5)  # Delay to avoid triggering API rate limits
        elif data and "Rate limit" not in str(data):
            # API returned but field missing - try to find the value
            found = False
            for k, v in data.items():
                if k not in ("d", "unixTs"):
                    try:
                        cache[key] = {"value": float(v), "date": data.get("d", ""), "fetched_at": now, "consecutive_failures": 0}
                        found = True
                    except: pass
                    break
            if not found:
                # Track failure — endpoint returns data but not in expected format
                prev = cache.get(key, {})
                cache[key] = {**prev, "consecutive_failures": prev.get("consecutive_failures", 0) + 1}
            calls_made += 1
            time.sleep(0.5)
        elif data is None:
            # fetch_json returned None — parse error or network error (not rate limit)
            prev = cache.get(key, {})
            fails = prev.get("consecutive_failures", 0) + 1
            cache[key] = {**prev, "consecutive_failures": fails}
            if fails >= 3:
                print(f"    ↳ {key} has failed {fails} times in a row")
            calls_made += 1  # Count failed requests against budget (they still hit the API)
            time.sleep(0.5)

    save_cache(cache)
    cached_count = sum(1 for v in cache.values() if v.get("value") is not None)
    print(f"  → Made {calls_made} API calls, {cached_count}/{len(BG_ENDPOINTS)} endpoints cached")
    return cache


# ─── Other Data Sources ─────────────────────────────────

def fetch_price_history():
    print("\n📊 Fetching BTC price history...")
    data = fetch_json(
        "https://api.blockchain.info/charts/market-price?timespan=5years&format=json&rollingAverage=1days",
        "Blockchain.info BTC price (5 years daily)"
    )
    if not data or "values" not in data or len(data["values"]) < 100:
        return None
    prices = [{"ts": d["x"]*1000, "date": datetime.fromtimestamp(d["x"], tz=timezone.utc).strftime("%Y-%m-%d"), "price": d["y"]} for d in data["values"]]

    time.sleep(1)
    mc_data = fetch_json(
        "https://api.blockchain.info/charts/market-cap?timespan=5years&format=json&rollingAverage=1days",
        "Blockchain.info market cap (5 years)"
    )
    market_caps = []
    if mc_data and "values" in mc_data:
        market_caps = [{"ts": d["x"]*1000, "cap": d["y"]} for d in mc_data["values"]]
    if not market_caps:
        market_caps = [{"ts": p["ts"], "cap": p["price"] * 19_800_000} for p in prices]

    return {"prices": prices, "marketCaps": market_caps}

def fetch_fear_greed():
    print("\n😱 Fetching Fear & Greed Index...")
    data = fetch_json("https://api.alternative.me/fng/?limit=365&format=json", "Alternative.me Fear & Greed")
    if not data or "data" not in data: return None
    return [{"ts": int(d["timestamp"])*1000, "date": datetime.fromtimestamp(int(d["timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d"), "value": int(d["value"]), "label": d["value_classification"]} for d in data["data"]]

def fetch_funding_rates():
    print("\n💰 Fetching funding rates...")
    data = fetch_json("https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=100", "Binance funding rates")
    if not data: return None
    return [{"ts": d["fundingTime"], "rate": float(d["fundingRate"])} for d in data]

def fetch_spot_price():
    """Fetch real-time BTC spot price from multiple sources for accuracy."""
    print("\n⚡ Fetching real-time BTC spot price...")
    sources = []

    # Source 1: Binance (most liquid exchange)
    data = fetch_json("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", "Binance spot")
    if data and "price" in data:
        sources.append(("Binance", float(data["price"])))

    time.sleep(0.3)

    # Source 2: CoinGecko
    data = fetch_json("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", "CoinGecko spot")
    if data and "bitcoin" in data:
        sources.append(("CoinGecko", float(data["bitcoin"]["usd"])))

    if not sources:
        print("  ⚠ No spot price available, will use Blockchain.info daily average")
        return None

    # Cross-validate: flag if sources disagree by more than 2%
    prices = [p for _, p in sources]
    avg = sum(prices) / len(prices)
    for name, p in sources:
        drift = abs(p - avg) / avg * 100
        if drift > 2:
            print(f"  ⚠ {name} drifts {drift:.1f}% from consensus — possible stale data")

    # Use Binance (highest liquidity) as primary, others as validation
    primary = sources[0]
    print(f"  → Spot price: ${primary[1]:,.0f} ({primary[0]})")
    return {"price": primary[1], "source": primary[0], "all": {n: p for n, p in sources}}

def fetch_open_interest():
    """Fetch BTC open interest from Binance Futures (free, no rate limit issues)."""
    print("\n📊 Fetching open interest from Binance...")
    data = fetch_json("https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT", "Binance OI (current)")
    if not data or "openInterest" not in data:
        return None
    oi_btc = float(data["openInterest"])

    # Get 30-day history for trend analysis
    time.sleep(0.3)
    hist = fetch_json("https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1d&limit=30", "Binance OI (30d history)")
    oi_history = []
    if hist:
        oi_history = [{"ts": d["timestamp"], "oi": float(d["sumOpenInterest"]), "oiUsd": float(d["sumOpenInterestValue"])} for d in hist]

    return {"current": oi_btc, "history": oi_history}

def fetch_hash_rate():
    print("\n⛏️  Fetching hash rate...")
    data = fetch_json("https://api.blockchain.info/charts/hash-rate?timespan=2years&format=json&rollingAverage=1days", "Hash rate (2yr)")
    if not data or "values" not in data: return None
    return [{"ts": d["x"]*1000, "hashRate": d["y"]} for d in data["values"]]

def fetch_miner_revenue():
    print("\n💵 Fetching miner revenue...")
    data = fetch_json("https://api.blockchain.info/charts/miners-revenue?timespan=2years&format=json&rollingAverage=1days", "Miner revenue (2yr)")
    if not data or "values" not in data: return None
    return [{"ts": d["x"]*1000, "revenue": d["y"]} for d in data["values"]]


# ─── Indicator Computation ──────────────────────────────

def bg(cache, key, default=None):
    """Get a BGeometrics cached value."""
    entry = cache.get(key)
    if entry and entry.get("value") is not None:
        return entry["value"]
    return default

def compute_indicators(price_hist, fear_greed, funding, hash_rate, miner_rev, bg_cache, spot=None, oi_data=None):
    prices = price_hist["prices"]
    daily_prices = [p["price"] for p in prices]
    bc_price = daily_prices[-1]
    current_date = prices[-1]["date"]

    # Use real-time spot price if available, otherwise fall back to Blockchain.info daily avg
    if spot and spot.get("price"):
        current_price = spot["price"]
        price_source = spot["source"]
        bc_drift = abs(current_price - bc_price) / current_price * 100
        print(f"\n🔢 Computing indicators (${current_price:,.0f} live via {price_source}, {current_date})...")
        if bc_drift > 1:
            print(f"  ℹ Blockchain.info daily avg: ${bc_price:,.0f} ({bc_drift:.1f}% behind spot)")
    else:
        current_price = bc_price
        price_source = "Blockchain.info"
        print(f"\n🔢 Computing indicators (${current_price:,.0f} via {price_source}, {current_date})...")

    ind = {}

    # ═══════════════════════════════════════════
    # DOMAIN 1: ON-CHAIN VALUATION (30% weight)
    # ═══════════════════════════════════════════

    # MVRV-Z Score — LIVE from BGeometrics
    mvrv_z = bg(bg_cache, "mvrv_zscore")
    ind["mvrvZScore"] = {
        "value": r(mvrv_z, 4) if mvrv_z else None,
        "live": mvrv_z is not None,
        "thresholds": {"deepBottom": -1.0, "bottom": 0, "neutral": 2.0, "danger": 7.0},
        "desc": "Below 0 = undervalued. Below -1 = deep bottom zone"
    }

    # NUPL — LIVE from BGeometrics
    nupl = bg(bg_cache, "nupl")
    nupl_zone = None
    if nupl is not None:
        if nupl < 0: nupl_zone = "Capitulation"
        elif nupl < 0.25: nupl_zone = "Hope / Fear"
        elif nupl < 0.50: nupl_zone = "Optimism"
        elif nupl < 0.75: nupl_zone = "Belief"
        else: nupl_zone = "Euphoria"
    ind["nupl"] = {
        "value": r(nupl, 4) if nupl else None,
        "zone": nupl_zone,
        "live": nupl is not None,
        "thresholds": {"capitulation": 0, "hopeFear": 0.25, "optimism": 0.5, "euphoria": 0.75},
        "desc": "Below 0 = network at unrealized loss = capitulation"
    }

    # Realized Price — LIVE from BGeometrics
    realized_price = bg(bg_cache, "realized_price")
    rp_ratio = current_price / realized_price if realized_price else None
    ind["realizedPrice"] = {
        "value": r(realized_price, 0) if realized_price else None,
        "ratio": r(rp_ratio, 4) if rp_ratio else None,
        "percentAbove": r((rp_ratio - 1) * 100, 1) if rp_ratio else None,
        "live": realized_price is not None,
        "desc": "Price below realized price = market at aggregate loss = bottom zone"
    }

    # Supply in Profit — LIVE from BGeometrics
    supply_profit = bg(bg_cache, "supply_profit")
    supply_current = 19_800_000  # approximate circulating supply
    supply_profit_pct = (supply_profit / supply_current * 100) if supply_profit else None
    ind["supplyInProfit"] = {
        "value": r(supply_profit_pct, 1) if supply_profit_pct else None,
        "absolute": r(supply_profit, 0) if supply_profit else None,
        "live": supply_profit is not None,
        "thresholds": {"deepBottom": 45, "bottom": 50, "stress": 60},
        "desc": "Below 50% = more supply at loss than profit = cycle bottom signal"
    }

    # Reserve Risk — LIVE from BGeometrics (NEW)
    reserve_risk = bg(bg_cache, "reserve_risk")
    ind["reserveRisk"] = {
        "value": reserve_risk,
        "live": reserve_risk is not None,
        "thresholds": {"greenZone": 0.002, "neutral": 0.008, "redZone": 0.02},
        "desc": "Below 0.002 = high conviction, low risk = ideal accumulation"
    }

    # SSR (Stablecoin Supply Ratio) — LIVE from BGeometrics (NEW)
    ssr = bg(bg_cache, "ssr")
    ind["ssr"] = {
        "value": r(ssr, 2) if ssr else None,
        "live": ssr is not None,
        "thresholds": {"highBuyingPower": 5, "neutral": 10, "lowBuyingPower": 20},
        "desc": "Low SSR = stablecoins have high buying power vs BTC = dry powder"
    }

    # RHODL Ratio — from BGeometrics (NEW)
    rhodl = bg(bg_cache, "rhodl_ratio")
    ind["rhodlRatio"] = {
        "value": rhodl,
        "live": rhodl is not None,
        "desc": "Low = long-term holders dominate = bottom zone. Avoids false positives"
    }

    # Thermocap Multiple — from BGeometrics
    thermo = bg(bg_cache, "thermocap_mult")
    ind["thermocapMultiple"] = {
        "value": thermo,
        "live": thermo is not None,
        "thresholds": {"bottom": 4, "neutral": 8, "top": 32},
        "desc": "Market cap vs cumulative miner revenue. Below 5 = deep value"
    }

    # ═══════════════════════════════════════════
    # DOMAIN 2: MINER HEALTH (15% weight)
    # ═══════════════════════════════════════════

    # Hash Ribbon — computed from blockchain.info hash rate
    hr_signal = None
    hr_30d = hr_60d = None
    if hash_rate and len(hash_rate) >= 60:
        hr_vals = [h["hashRate"] for h in hash_rate]
        hr_30d = sma(hr_vals, 30)
        hr_60d = sma(hr_vals, 60)
        if hr_30d and hr_60d:
            if hr_30d < hr_60d:
                hr_signal = "CAPITULATION"
            else:
                prev_30 = sma(hr_vals[:-1], 30)
                prev_60 = sma(hr_vals[:-1], 60)
                if prev_30 and prev_60 and prev_30 < prev_60:
                    hr_signal = "BUY SIGNAL"
                else:
                    hr_signal = "RECOVERY"
    ind["hashRibbon"] = {
        "signal": hr_signal,
        "ma30d": r(hr_30d, 0) if hr_30d else None,
        "ma60d": r(hr_60d, 0) if hr_60d else None,
        "live": True,
        "desc": "Buy signal = 30d hash MA crosses above 60d after capitulation"
    }

    # Puell Multiple — computed from blockchain.info miner revenue
    puell = None
    if miner_rev and len(miner_rev) >= 365:
        revenues = [m["revenue"] for m in miner_rev]
        avg_365 = sma(revenues, 365)
        if avg_365 and avg_365 > 0:
            puell = revenues[-1] / avg_365
    ind["puellMultiple"] = {
        "value": r(puell, 4) if puell else None,
        "live": True,
        "thresholds": {"deepGreen": 0.3, "green": 0.5, "neutral": 1.0, "red": 3.0},
        "desc": "Below 0.5 = miner capitulation = accumulation zone"
    }

    # ═══════════════════════════════════════════
    # DOMAIN 3: TECHNICAL / PRICE (20% weight)
    # ═══════════════════════════════════════════

    # Mayer Multiple
    sma200d = sma(daily_prices, 200)
    mayer = current_price / sma200d if sma200d else None
    ind["mayerMultiple"] = {
        "value": r(mayer, 4) if mayer else None,
        "sma200d": r(sma200d, 0) if sma200d else None,
        "live": True,
        "thresholds": {"deepBottom": 0.6, "bottom": 0.8, "neutral": 1.0, "top": 2.4},
        "desc": "Price / 200-day MA. Below 0.8 = oversold"
    }

    # 200-Week MA
    weekly_prices = daily_prices[::7]
    wma200 = sma(weekly_prices, 200)
    wma200_ratio = current_price / wma200 if wma200 else None
    ind["wma200"] = {
        "value": r(wma200, 0) if wma200 else None,
        "ratio": r(wma200_ratio, 4) if wma200_ratio else None,
        "percentAbove": r((wma200_ratio - 1) * 100, 1) if wma200_ratio else None,
        "live": True,
        "desc": "Historic cycle floor. Price at or below = major buy zone"
    }

    # Pi Cycle Bottom
    ema150 = ema(daily_prices, 150)
    sma471 = sma(daily_prices, 471)
    pi_line = sma471 * 0.475 if sma471 else None
    pi_signal = None
    if ema150 and pi_line:
        pi_signal = "BOTTOM ZONE" if ema150 < pi_line else "ABOVE"
    ind["piCycleBottom"] = {
        "signal": pi_signal,
        "ema150": r(ema150, 0) if ema150 else None,
        "threshold": r(pi_line, 0) if pi_line else None,
        "live": True,
        "desc": "150d EMA below 471d SMA x 0.475 = cycle bottom"
    }

    # Cycle Timing — auto-detect ATH from price history
    ath_price = max(p["price"] for p in prices)
    ath_idx = next(i for i, p in enumerate(prices) if p["price"] == ath_price)
    ath_date = datetime.strptime(prices[ath_idx]["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    days_since_ath = (datetime.now(tz=timezone.utc) - ath_date).days
    avg_bottom = 383
    drawdown = ((current_price - ath_price) / ath_price) * 100
    cycle_progress = min(days_since_ath / avg_bottom, 1.0)
    est_bottom = datetime.fromtimestamp(ath_date.timestamp() + avg_bottom * 86400, tz=timezone.utc)

    ind["cycleTiming"] = {
        "daysSinceATH": days_since_ath,
        "avgDaysToBottom": avg_bottom,
        "cycleProgress": r(cycle_progress, 3),
        "estimatedBottom": est_bottom.strftime("%Y-%m-%d"),
        "drawdownPct": r(drawdown, 1),
        "athPrice": ath_price,
        "live": True,
        "desc": f"Day {days_since_ath} of ~{avg_bottom}. Est. bottom: {est_bottom.strftime('%b %Y')}"
    }

    # Rainbow Chart
    genesis_ts = datetime(2009, 1, 9, tzinfo=timezone.utc).timestamp() * 1000
    days_since_genesis = (time.time() * 1000 - genesis_ts) / (1000 * 60 * 60 * 24)
    rainbow_center = 10 ** (-17.31 + 5.82 * math.log10(days_since_genesis))
    rainbow_bands = {
        "Fire Sale": rainbow_center * 0.32, "BUY!": rainbow_center * 0.52,
        "Accumulate": rainbow_center * 0.82, "Still Cheap": rainbow_center * 1.25,
        "HODL!": rainbow_center * 1.85, "Is this a bubble?": rainbow_center * 2.75,
        "FOMO intensifies": rainbow_center * 4.0, "Sell. Seriously.": rainbow_center * 5.8,
        "Max Bubble": rainbow_center * 8.5,
    }
    current_band = "Max Bubble"
    band_names = list(rainbow_bands.keys())
    for i in range(len(band_names) - 1):
        if current_price <= rainbow_bands[band_names[i + 1]]:
            current_band = band_names[i]
            break
    ind["rainbowChart"] = {
        "currentBand": current_band,
        "bands": {k: round(v) for k, v in rainbow_bands.items()},
        "live": True,
        "desc": "Logarithmic regression bands. Lower = deeper value"
    }

    # ═══════════════════════════════════════════
    # DOMAIN 4: SENTIMENT & POSITIONING (15%)
    # ═══════════════════════════════════════════

    # SOPR — LIVE from BGeometrics
    sopr = bg(bg_cache, "sopr")
    ind["sopr"] = {
        "value": r(sopr, 4) if sopr else None,
        "live": sopr is not None,
        "desc": "Below 1.0 = sellers at a loss = capitulation"
    }

    # LTH-SOPR — LIVE from BGeometrics
    lth_sopr = bg(bg_cache, "lth_sopr")
    ind["lthSopr"] = {
        "value": r(lth_sopr, 4) if lth_sopr else None,
        "live": lth_sopr is not None,
        "desc": "Long-term holders selling at loss = extreme capitulation"
    }

    # Fear & Greed
    fg_current = fg_avg30 = None
    ef_days = 0
    if fear_greed:
        fg_current = fear_greed[0]
        last30 = [f["value"] for f in fear_greed[:30]]
        fg_avg30 = sum(last30) / len(last30) if last30 else None
        for f in fear_greed:
            if f["value"] < 25: ef_days += 1
            else: break
    ind["fearGreed"] = {
        "current": fg_current["value"] if fg_current else None,
        "label": fg_current["label"] if fg_current else None,
        "avg30d": r(fg_avg30, 1) if fg_avg30 else None,
        "extremeFearDays": ef_days,
        "live": True,
        "desc": "Sustained extreme fear (< 25) = contrarian buy"
    }

    # Funding Rates
    curr_fr = avg_fr = None
    neg_count = 0
    if funding:
        curr_fr = funding[-1]["rate"]
        recent = funding[-30:]
        avg_fr = sum(f["rate"] for f in recent) / len(recent)
        neg_count = sum(1 for f in recent if f["rate"] < 0)
    ind["fundingRates"] = {
        "current": r(curr_fr, 6) if curr_fr else None,
        "avg10d": r(avg_fr, 6) if avg_fr else None,
        "negativePeriods": neg_count,
        "live": True,
        "desc": "Negative = shorts paying longs = bearish positioning"
    }

    # NVT Signal — from BGeometrics (NEW)
    nvts = bg(bg_cache, "nvts")
    ind["nvtSignal"] = {
        "value": r(nvts, 2) if nvts else None,
        "live": nvts is not None,
        "desc": "Network Value to Transactions. Low = undervalued network"
    }

    # ═══════════════════════════════════════════
    # DOMAIN 5: EXCHANGE & LIQUIDITY (10%)
    # ═══════════════════════════════════════════

    # Exchange Reserves — from BGeometrics (NEW)
    exch_reserve = bg(bg_cache, "exchange_reserve")
    ind["exchangeReserves"] = {
        "value": r(exch_reserve, 0) if exch_reserve else None,
        "live": exch_reserve is not None,
        "desc": "Coins on exchanges. Declining = accumulation (bullish)"
    }

    # Exchange Netflow — computed from reserve changes, or from BGeometrics
    exch_netflow_bg = bg(bg_cache, "exchange_netflow")
    # Also compute netflow from reserve history if available
    reserve_prev = bg_cache.get("exchange_reserve_prev", {}).get("value")
    computed_netflow = None
    if exch_reserve is not None and reserve_prev is not None:
        computed_netflow = exch_reserve - reserve_prev  # positive = inflow, negative = outflow
    netflow_val = exch_netflow_bg if exch_netflow_bg is not None else computed_netflow
    ind["exchangeNetflow"] = {
        "value": r(netflow_val, 2) if netflow_val is not None else None,
        "live": netflow_val is not None,
        "source": "BGeometrics" if exch_netflow_bg is not None else "computed" if computed_netflow is not None else None,
        "desc": "Negative = outflows = coins leaving exchanges = accumulation"
    }

    # Open Interest — from Binance Futures (reliable, free)
    oi_current = None
    oi_change_pct = None
    if oi_data:
        oi_current = oi_data.get("current")
        hist = oi_data.get("history", [])
        if hist and oi_current:
            oi_30d_ago = hist[0]["oi"] if hist else None
            if oi_30d_ago and oi_30d_ago > 0:
                oi_change_pct = ((oi_current - oi_30d_ago) / oi_30d_ago) * 100
    ind["openInterest"] = {
        "value": r(oi_current, 0) if oi_current else None,
        "changePct30d": r(oi_change_pct, 1) if oi_change_pct is not None else None,
        "live": oi_current is not None,
        "source": "Binance",
        "desc": "Total derivatives positions. Large decline = leverage reset = healthier market"
    }

    # ═══════════════════════════════════════════
    # META
    # ═══════════════════════════════════════════

    ind["_meta"] = {
        "computedAt": datetime.now(tz=timezone.utc).isoformat(),
        "currentPrice": r(current_price),
        "currentDate": current_date,
        "priceSource": price_source,
        "priceSources": spot.get("all") if spot else {"Blockchain.info": bc_price},
    }

    # Price sparkline (last 180 days)
    ind["_priceHistory"] = [{"d": p["date"], "p": round(p["price"])} for p in prices[-180:]]

    # ═══════════════════════════════════════════
    # COMPOSITE SCORING
    # ═══════════════════════════════════════════

    ind["_composite"] = compute_composite(ind)
    return ind


# ─── Composite Scoring ──────────────────────────────────

def score_val(val, ranges):
    """Score a value. ranges = list of (max_threshold, score) in ascending order."""
    if val is None: return None
    for threshold, score in ranges:
        if val <= threshold:
            return score
    return ranges[-1][1] if ranges else 0

def compute_composite(ind):
    """
    Score each indicator 0-10, group into domains, weight to 0-100.

    Scoring philosophy:
    - 10 = historically confirmed bottom signal firing
    - 7-9 = approaching/in bottom territory
    - 4-6 = neutral, mixed signals
    - 1-3 = not yet showing bottom characteristics
    - 0 = opposite of bottom (euphoria/top territory)
    """

    # ── Domain 1: On-Chain Valuation (30%) ──
    d1 = []

    # MVRV-Z: <-1 = 10, <0 = 8, <0.5 = 5, <1 = 3, <2 = 1
    v = ind["mvrvZScore"]["value"]
    if v is not None:
        s = score_val(v, [(-1.5, 10), (-1, 9), (-0.5, 8), (0, 7), (0.5, 5), (1, 3), (2, 1), (999, 0)])
        d1.append(("MVRV-Z Score", s, 2.5))

    # NUPL: <-0.2 = 10, <0 = 8, <0.15 = 6, <0.25 = 4, <0.5 = 1
    v = ind["nupl"]["value"]
    if v is not None:
        s = score_val(v, [(-0.2, 10), (0, 8), (0.1, 6), (0.2, 5), (0.3, 3), (0.5, 1), (999, 0)])
        d1.append(("NUPL", s, 2))

    # Realized Price ratio: <0.8 = 10, <1.0 = 8, <1.1 = 6, <1.2 = 4, <1.3 = 2
    v = ind["realizedPrice"]["ratio"]
    if v is not None:
        s = score_val(v, [(0.75, 10), (0.85, 9), (1.0, 8), (1.1, 6), (1.2, 4), (1.3, 2), (999, 0)])
        d1.append(("Realized Price", s, 2))

    # Supply in Profit: <45% = 10, <50% = 8, <55% = 6, <65% = 3
    v = ind["supplyInProfit"]["value"]
    if v is not None:
        s = score_val(v, [(45, 10), (50, 9), (55, 7), (60, 5), (70, 3), (80, 1), (999, 0)])
        d1.append(("Supply in Profit", s, 2))

    # Reserve Risk: <0.001 = 10, <0.002 = 8, <0.005 = 5, <0.01 = 2
    v = ind["reserveRisk"]["value"]
    if v is not None:
        s = score_val(v, [(0.0005, 10), (0.001, 9), (0.002, 7), (0.005, 4), (0.01, 2), (999, 0)])
        d1.append(("Reserve Risk", s, 2))

    # SSR: <4 = 10, <6 = 7, <10 = 4, <15 = 2
    v = ind["ssr"]["value"]
    if v is not None:
        s = score_val(v, [(3, 10), (5, 8), (7, 6), (10, 4), (15, 2), (999, 0)])
        d1.append(("Stablecoin Ratio", s, 1.5))

    # Thermocap: <4 = 10, <6 = 7, <10 = 4
    v = ind["thermocapMultiple"]["value"]
    if v is not None:
        s = score_val(v, [(4, 10), (6, 8), (8, 6), (12, 3), (999, 0)])
        d1.append(("Thermocap", s, 1))

    # ── Domain 2: Miner Health (15%) ──
    d2 = []

    sig = ind["hashRibbon"]["signal"]
    if sig:
        s = {"BUY SIGNAL": 10, "CAPITULATION": 7, "RECOVERY": 4}.get(sig, 2)
        d2.append(("Hash Ribbon", s, 2))

    v = ind["puellMultiple"]["value"]
    if v is not None:
        s = score_val(v, [(0.3, 10), (0.5, 8), (0.7, 5), (1.0, 3), (1.5, 1), (999, 0)])
        d2.append(("Puell Multiple", s, 1.5))

    # ── Domain 3: Technical / Price (20%) ──
    d3 = []

    v = ind["mayerMultiple"]["value"]
    if v is not None:
        s = score_val(v, [(0.5, 10), (0.6, 9), (0.7, 7), (0.8, 6), (0.9, 4), (1.0, 2), (999, 0)])
        d3.append(("Mayer Multiple", s, 2))

    v = ind["wma200"]["ratio"]
    if v is not None:
        s = score_val(v, [(0.9, 10), (1.0, 9), (1.1, 7), (1.15, 5), (1.3, 3), (1.5, 1), (999, 0)])
        d3.append(("200-Week MA", s, 2))

    if ind["piCycleBottom"]["signal"] == "BOTTOM ZONE":
        d3.append(("Pi Cycle Bottom", 10, 1.5))
    else:
        d3.append(("Pi Cycle Bottom", 1, 1.5))

    dd = abs(ind["cycleTiming"]["drawdownPct"])
    s = score_val(dd, [(25, 0), (35, 2), (45, 4), (55, 6), (65, 7), (75, 9), (999, 10)])
    d3.append(("Drawdown Depth", s, 1))

    band_scores = {"Fire Sale": 10, "BUY!": 8, "Accumulate": 6, "Still Cheap": 3, "HODL!": 1}
    rs = band_scores.get(ind["rainbowChart"]["currentBand"], 0)
    d3.append(("Rainbow Chart", rs, 1))

    # ── Domain 4: Sentiment & Positioning (15%) ──
    d4 = []

    v = ind["sopr"]["value"]
    if v is not None:
        s = score_val(v, [(0.90, 10), (0.95, 8), (0.98, 6), (1.00, 5), (1.02, 3), (999, 0)])
        d4.append(("SOPR", s, 2))

    v = ind["lthSopr"]["value"]
    if v is not None:
        s = score_val(v, [(0.90, 10), (0.95, 9), (1.00, 7), (1.05, 4), (1.2, 2), (999, 0)])
        d4.append(("LTH-SOPR", s, 1.5))

    v = ind["fearGreed"]["current"]
    if v is not None:
        s = score_val(v, [(10, 10), (15, 9), (20, 8), (25, 7), (35, 4), (50, 2), (999, 0)])
        d4.append(("Fear & Greed", s, 1.5))

    ef = ind["fearGreed"]["extremeFearDays"]
    s = score_val(-ef, [(-30, 10), (-21, 8), (-14, 6), (-7, 4), (-3, 2), (999, 0)])  # negate because lower ef = less signal
    d4.append(("Fear Duration", s, 1))

    v = ind["fundingRates"]["avg10d"]
    if v is not None:
        s = score_val(v, [(-0.01, 10), (-0.005, 8), (-0.001, 6), (0, 4), (0.005, 1), (999, 0)])
        d4.append(("Funding Rates", s, 1))

    # ── Domain 5: Exchange & Liquidity (10%) ──
    d5 = []

    # Exchange netflow: negative = outflow = bullish
    v = ind["exchangeNetflow"]["value"]
    if v is not None:
        s = 8 if v < -500 else 6 if v < -100 else 4 if v < 0 else 2 if v < 500 else 0
        d5.append(("Exchange Netflow", s, 2))

    # SSR already in D1, NVT here
    v = ind["nvtSignal"]["value"]
    if v is not None:
        # NVT Signal typical range: 20-200+. Low = undervalued network, High = overvalued
        # Historically: <45 oversold, 45-80 neutral, >100 overvalued
        s = score_val(v, [(30, 10), (45, 9), (60, 7), (80, 5), (100, 3), (150, 1), (999, 0)])
        d5.append(("NVT Signal", s, 1.5))

    # Open Interest: score based on 30d change — decline = leverage unwind = healthier
    oi_chg = ind["openInterest"].get("changePct30d")
    if oi_chg is not None:
        # Big decline in OI = leverage flushed = bullish setup
        s = score_val(oi_chg, [(-40, 10), (-25, 8), (-15, 6), (-5, 4), (5, 2), (999, 0)])
        d5.append(("Open Interest", s, 1))
    elif ind["openInterest"]["value"] is not None:
        d5.append(("Open Interest", 5, 1))  # have data but no trend yet

    # ── Domain 6: Cycle Timing (10%) ──
    d6 = []

    cp = ind["cycleTiming"]["cycleProgress"]
    s = score_val(cp, [(0.2, 0), (0.3, 2), (0.4, 3), (0.55, 4), (0.7, 6), (0.85, 8), (0.95, 9), (999, 10)])
    d6.append(("Cycle Progress", s, 2))

    # RHODL (if available)
    v = ind["rhodlRatio"]["value"]
    if v is not None:
        # Low RHODL = bottom zone. Historically bottoms below ~500-1000
        s = score_val(v, [(300, 10), (500, 8), (1000, 5), (2000, 3), (5000, 1), (999, 0)])
        d6.append(("RHODL Ratio", s, 1.5))

    # ── Aggregate ──
    def domain_avg(items):
        if not items: return 0, []
        tw = sum(w for _, _, w in items)
        ts = sum(s * w for _, s, w in items)
        return round(ts / tw, 1) if tw > 0 else 0, [{"name": n, "score": s, "weight": w} for n, s, w in items]

    domains = {}
    for key, label, weight, items in [
        ("onChain",   "On-Chain Valuation",     0.30, d1),
        ("miner",     "Miner Health",           0.15, d2),
        ("technical", "Technical / Price",      0.20, d3),
        ("sentiment", "Sentiment & Positioning", 0.15, d4),
        ("exchange",  "Exchange & Liquidity",   0.10, d5),
        ("cycle",     "Cycle Timing",           0.10, d6),
    ]:
        score, items_out = domain_avg(items)
        domains[key] = {"score": score, "weight": weight, "items": items_out, "label": label}

    # Redistribute weight from domains with no data yet
    active_weight = sum(d["weight"] for d in domains.values() if d["items"])
    scale = 1.0 / active_weight if active_weight > 0 else 1.0

    for d in domains.values():
        if d["items"]:
            ew = d["weight"] * scale
            d["effectiveWeight"] = round(ew, 4)
            d["contribution"] = round(d["score"] * ew * 10, 1)
        else:
            d["effectiveWeight"] = 0
            d["contribution"] = 0
            d["noData"] = True

    composite = round(sum(d["contribution"] for d in domains.values()), 1)

    if composite >= 75:   zone, label, color = "STRONG_BUY", "STRONG BUY", "#22C55E"
    elif composite >= 50: zone, label, color = "ACCUMULATE", "ACCUMULATE", "#EAB308"
    elif composite >= 25: zone, label, color = "WATCHING", "WATCHING", "#FB923C"
    else:                 zone, label, color = "NO_ENTRY", "NO ENTRY", "#EF4444"

    return {"score": composite, "zone": zone, "zoneLabel": label, "zoneColor": color, "domains": domains}


# ─── Main ───────────────────────────────────────────────

def main():
    print("╔══════════════════════════════════════════╗")
    print("║  Bitcoin Re-Entry Signal v2 — Engine     ║")
    print("╚══════════════════════════════════════════╝")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Log rotation: keep last 500 lines to prevent cron.log from growing forever
    log_file = DATA_DIR / "cron.log"
    if log_file.exists():
        try:
            lines = log_file.read_text().splitlines()
            if len(lines) > 2000:
                log_file.write_text("\n".join(lines[-500:]) + "\n")
                print(f"  ↳ Trimmed cron.log from {len(lines)} to 500 lines")
        except: pass

    # Fetch BGeometrics (cached, rate-limited)
    bg_cache = fetch_bgeometrics()

    # Store exchange reserve history for netflow computation
    exch_reserve_entry = bg_cache.get("exchange_reserve")
    if exch_reserve_entry and exch_reserve_entry.get("value") is not None:
        prev = bg_cache.get("exchange_reserve_prev")
        # Only update prev if the current value is from a different date
        if not prev or prev.get("date") != exch_reserve_entry.get("date"):
            bg_cache["exchange_reserve_prev"] = {
                "value": exch_reserve_entry["value"],
                "date": exch_reserve_entry.get("date", ""),
            }
            save_cache(bg_cache)

    # Fetch real-time spot price first
    spot = fetch_spot_price()

    # Fetch other sources
    time.sleep(0.5)
    price_hist = fetch_price_history()
    if not price_hist:
        print("\n❌ Failed to fetch price history")
        sys.exit(1)

    time.sleep(1)
    fear_greed = fetch_fear_greed()
    time.sleep(1)
    funding = fetch_funding_rates()
    time.sleep(1)
    oi_data = fetch_open_interest()
    time.sleep(1)
    hash_rate = fetch_hash_rate()
    time.sleep(1)
    miner_rev = fetch_miner_revenue()

    # Compute
    indicators = compute_indicators(price_hist, fear_greed, funding, hash_rate, miner_rev, bg_cache, spot, oi_data)

    # Save
    out = DATA_DIR / "indicators.json"
    with open(out, "w") as f:
        json.dump(indicators, f, indent=2)
    print(f"\n💾 Saved to {out}")

    # Summary
    c = indicators["_composite"]
    print()
    print("╔══════════════════════════════════════════════╗")
    print(f"║  COMPOSITE SCORE: {c['score']:>5.1f}  [{c['zoneLabel']:^12}]    ║")
    print("╠══════════════════════════════════════════════╣")
    for d in c["domains"].values():
        pct = int(d["weight"] * 100)
        print(f"║  {d['label']:<30} {d['score']:>4}/10  ({pct}%) ║")
    print("╚══════════════════════════════════════════════╝")

    # Count live vs cached
    live_count = sum(1 for k, v in indicators.items() if isinstance(v, dict) and v.get("live"))
    total = sum(1 for k, v in indicators.items() if isinstance(v, dict) and "live" in v)
    cached_count = sum(1 for k, v in bg_cache.items() if v.get("value") is not None)
    print(f"\n  📡 {live_count}/{total} indicators live | {cached_count}/{len(BG_ENDPOINTS)} BGeometrics cached")
    print(f"  💡 Run again in 1 hour to fetch remaining BGeometrics data")


if __name__ == "__main__":
    main()
