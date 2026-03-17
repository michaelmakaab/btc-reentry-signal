#!/usr/bin/env python3
"""
Bitcoin Re-Entry Signal — Historical Data Downloader

One-time script to download full historical data for backtesting.
Saves everything to data/history/ as JSON files.

Data sources:
  - Blockchain.com: Price, hash rate, miner revenue (timespan=all, no rate limit)
  - BGeometrics (bitcoin-data.com): On-chain metrics (8 req/hr, 15 req/day free)
  - Alternative.me: Fear & Greed Index (limit=0, no rate limit)
  - Binance: Funding rates (paginated, from Sept 2019)
"""

import json, os, sys, time
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from pathlib import Path

HIST_DIR = Path(__file__).parent.parent / "data" / "history"
HIST_DIR.mkdir(parents=True, exist_ok=True)

def fetch_json(url, label, timeout=60):
    """Fetch JSON from URL with retries."""
    for attempt in range(3):
        try:
            req = Request(url, headers={
                "User-Agent": "BTC-ReEntry-Backtest/1.0",
                "Accept": "application/json"
            })
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode()
                if not raw.strip():
                    print(f"  ✗ {label}: empty response")
                    return None
                data = json.loads(raw)
                # Check rate limit
                if isinstance(data, dict) and data.get("error", {}).get("code", "").startswith("RATE_LIMIT"):
                    print(f"  ⏳ {label}: RATE LIMITED — wait and retry")
                    return "RATE_LIMITED"
                return data
        except HTTPError as e:
            if e.code == 429:
                print(f"  ⏳ {label}: HTTP 429 rate limited (attempt {attempt+1})")
                time.sleep(60)
                continue
            elif e.code == 403:
                print(f"  ✗ {label}: HTTP 403 Forbidden")
                return None
            print(f"  ✗ {label}: HTTP {e.code}")
            return None
        except Exception as e:
            print(f"  ✗ {label}: {e}")
            if attempt < 2:
                time.sleep(5)
    return None


def save(name, data):
    """Save data to history directory."""
    path = HIST_DIR / f"{name}.json"
    with open(path, "w") as f:
        json.dump(data, f)
    count = len(data) if isinstance(data, list) else "object"
    print(f"  ✓ Saved {name}.json ({count} entries)")


def download_blockchain_com():
    """Download price, hash rate, miner revenue from blockchain.com (no rate limit)."""
    print("\n═══ Blockchain.com ═══")

    charts = {
        "price": ("market-price", "BTC daily price"),
        "market_cap": ("market-cap", "BTC market cap"),
        "hash_rate": ("hash-rate", "Hash rate"),
        "miner_revenue": ("miners-revenue", "Miner revenue"),
        "difficulty": ("difficulty", "Mining difficulty"),
    }

    for key, (chart, label) in charts.items():
        path = HIST_DIR / f"bc_{key}.json"
        if path.exists():
            existing = json.load(open(path))
            if isinstance(existing, list) and len(existing) > 1000:
                print(f"  ⏭ {label}: already downloaded ({len(existing)} points)")
                continue

        print(f"  📥 {label}...")
        url = f"https://api.blockchain.info/charts/{chart}?timespan=all&format=json&sampled=false"
        data = fetch_json(url, label, timeout=120)
        if data and "values" in data:
            # Convert to clean format
            points = []
            for d in data["values"]:
                dt = datetime.fromtimestamp(d["x"], tz=timezone.utc)
                points.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "value": d["y"]
                })
            save(f"bc_{key}", points)
        else:
            print(f"  ✗ {label}: no data")
        time.sleep(2)


def download_bgeometrics():
    """Download on-chain metrics from bitcoin-data.com (rate limited: 8/hr, 15/day)."""
    print("\n═══ BGeometrics (bitcoin-data.com) ═══")
    print("  ⚠ Free tier: 8 requests/hour, 15/day")
    print("  This will take multiple runs if rate limited.\n")

    endpoints = [
        ("bg_mvrv_zscore",    "/v1/mvrv-zscore",       "mvrvZscore",        "MVRV Z-Score"),
        ("bg_nupl",           "/v1/nupl",               "nupl",              "NUPL"),
        ("bg_sopr",           "/v1/sopr",               "sopr",              "SOPR"),
        ("bg_realized_price", "/v1/realized-price",     "realizedPrice",     "Realized Price"),
        ("bg_reserve_risk",   "/v1/reserve-risk",       "reserveRisk",       "Reserve Risk"),
        ("bg_supply_profit",  "/v1/supply-profit",      "supplyProfit",      "Supply in Profit"),
        ("bg_lth_sopr",       "/v1/lth-sopr",           "lthSopr",          "LTH-SOPR"),
        ("bg_sth_sopr",       "/v1/sth-sopr",           "sthSopr",          "STH-SOPR"),
        ("bg_ssr",            "/v1/ssr",                "ssrStablecoin",     "Stablecoin Supply Ratio"),
        ("bg_rhodl_ratio",    "/v1/rhodl-ratio",        "rhodlRatio1m",      "RHODL Ratio"),
        ("bg_nvts",           "/v1/nvts",               "nvts",              "NVT Signal"),
        ("bg_thermocap",      "/v1/thermocap-multiple", "thermocapMultiple", "Thermocap Multiple"),
        ("bg_exchange_reserve", "/v1/exchange-reserve-btc", "exchangeReserveBtc", "Exchange Reserve"),
        ("bg_exchange_netflow", "/v1/exchange-netflow-btc", "exchangeNetflowBtc", "Exchange Netflow"),
    ]

    downloaded = 0
    rate_limited = False

    for filename, path, value_key, label in endpoints:
        fpath = HIST_DIR / f"{filename}.json"
        if fpath.exists():
            existing = json.load(open(fpath))
            if isinstance(existing, list) and len(existing) > 500:
                print(f"  ⏭ {label}: already downloaded ({len(existing)} points)")
                continue

        if rate_limited:
            print(f"  ⏭ {label}: skipping (rate limited)")
            continue

        print(f"  📥 {label}...")
        url = f"https://bitcoin-data.com{path}"
        data = fetch_json(url, label, timeout=120)

        if data == "RATE_LIMITED":
            rate_limited = True
            print(f"  ⚠ Rate limited after {downloaded} downloads. Run again later for remaining.")
            continue

        if data and isinstance(data, list) and len(data) > 0:
            # Normalize: extract date and value
            points = []
            for item in data:
                date = item.get("d") or item.get("theDay") or ""
                value = item.get(value_key)
                if date and value is not None:
                    try:
                        points.append({"date": date, "value": float(value)})
                    except (ValueError, TypeError):
                        pass
            # Sort by date
            points.sort(key=lambda x: x["date"])
            save(filename, points)
            downloaded += 1
        else:
            print(f"  ✗ {label}: no data or unexpected format")

        # Respect rate limits: wait between calls
        time.sleep(10)

    if rate_limited:
        remaining = sum(1 for f, _, _, _ in endpoints if not (HIST_DIR / f"{f}.json").exists())
        print(f"\n  ⚠ {remaining} endpoints remaining. Run this script again in ~1 hour.")


def download_fear_greed():
    """Download full Fear & Greed history from Alternative.me (Feb 2018+)."""
    print("\n═══ Alternative.me Fear & Greed ═══")

    path = HIST_DIR / "fg_fear_greed.json"
    if path.exists():
        existing = json.load(open(path))
        if isinstance(existing, list) and len(existing) > 1000:
            print(f"  ⏭ Fear & Greed: already downloaded ({len(existing)} points)")
            return

    print("  📥 Fear & Greed Index (full history)...")
    data = fetch_json("https://api.alternative.me/fng/?limit=0&format=json", "Fear & Greed", timeout=60)
    if data and "data" in data:
        points = []
        for d in data["data"]:
            dt = datetime.fromtimestamp(int(d["timestamp"]), tz=timezone.utc)
            points.append({
                "date": dt.strftime("%Y-%m-%d"),
                "value": int(d["value"]),
                "label": d["value_classification"]
            })
        # Sort chronologically (API returns newest first)
        points.sort(key=lambda x: x["date"])
        save("fg_fear_greed", points)
    else:
        print("  ✗ Fear & Greed: no data")


def download_funding_rates():
    """Download funding rate history from Binance (Sept 2019+, paginated)."""
    print("\n═══ Binance Funding Rates ═══")

    path = HIST_DIR / "bn_funding_rates.json"
    if path.exists():
        existing = json.load(open(path))
        if isinstance(existing, list) and len(existing) > 5000:
            print(f"  ⏭ Funding rates: already downloaded ({len(existing)} points)")
            return

    print("  📥 Funding rates (paginated, may take a minute)...")
    all_rates = []
    start_time = int(datetime(2019, 9, 1, tzinfo=timezone.utc).timestamp() * 1000)

    while True:
        url = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&startTime={start_time}&limit=1000"
        data = fetch_json(url, "Binance funding", timeout=30)
        if not data or not isinstance(data, list) or len(data) == 0:
            break

        for d in data:
            dt = datetime.fromtimestamp(d["fundingTime"] / 1000, tz=timezone.utc)
            all_rates.append({
                "date": dt.strftime("%Y-%m-%d"),
                "datetime": dt.strftime("%Y-%m-%d %H:%M"),
                "rate": float(d["fundingRate"]),
                "ts": d["fundingTime"]
            })

        # Next page
        start_time = data[-1]["fundingTime"] + 1
        if len(data) < 1000:
            break
        time.sleep(0.5)

    if all_rates:
        save("bn_funding_rates", all_rates)
    else:
        print("  ✗ Funding rates: no data")


def status_report():
    """Print summary of what's been downloaded."""
    print("\n═══ Download Status ═══")
    expected = [
        "bc_price", "bc_market_cap", "bc_hash_rate", "bc_miner_revenue", "bc_difficulty",
        "bg_mvrv_zscore", "bg_nupl", "bg_sopr", "bg_realized_price", "bg_reserve_risk",
        "bg_supply_profit", "bg_lth_sopr", "bg_sth_sopr", "bg_ssr", "bg_rhodl_ratio",
        "bg_nvts", "bg_thermocap", "bg_exchange_reserve", "bg_exchange_netflow",
        "fg_fear_greed", "bn_funding_rates",
    ]

    ready = 0
    missing = []
    for name in expected:
        path = HIST_DIR / f"{name}.json"
        if path.exists():
            data = json.load(open(path))
            count = len(data) if isinstance(data, list) else "?"
            first = data[0]["date"] if isinstance(data, list) and data else "?"
            last = data[-1]["date"] if isinstance(data, list) and data else "?"
            print(f"  ✓ {name:30s} {count:>6} points  ({first} → {last})")
            ready += 1
        else:
            print(f"  ✗ {name:30s} MISSING")
            missing.append(name)

    print(f"\n  {ready}/{len(expected)} datasets ready")
    if missing:
        bg_missing = [m for m in missing if m.startswith("bg_")]
        if bg_missing:
            print(f"  ⚠ {len(bg_missing)} BGeometrics endpoints remaining — run again in ~1 hour")
    else:
        print("  ✅ All data downloaded! Ready to run backtest.")


def main():
    print("Bitcoin Re-Entry Signal — Historical Data Downloader")
    print(f"Saving to: {HIST_DIR}\n")

    # Phase 1: Blockchain.com (no rate limits)
    download_blockchain_com()

    # Phase 2: Fear & Greed (no rate limits)
    download_fear_greed()

    # Phase 3: Binance funding rates (generous limits)
    download_funding_rates()

    # Phase 4: BGeometrics (rate limited — may need multiple runs)
    download_bgeometrics()

    # Summary
    status_report()


if __name__ == "__main__":
    main()
