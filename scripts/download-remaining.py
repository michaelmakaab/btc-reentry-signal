#!/usr/bin/env python3
"""
Retry downloading the 6 remaining BGeometrics endpoints.
Tries every 5 minutes until all succeed or 2 hours pass.
"""

import json, time
from urllib.request import urlopen, Request
from pathlib import Path

HIST_DIR = Path(__file__).parent.parent / "data" / "history"

ENDPOINTS = [
    ("bg_mvrv_zscore",      "/v1/mvrv-zscore",         "mvrvZscore",        "MVRV Z-Score"),
    ("bg_rhodl_ratio",      "/v1/rhodl-ratio",          "rhodl1m",           "RHODL Ratio"),
    ("bg_nvts",             "/v1/nvts",                 "nvts",              "NVT Signal"),
    ("bg_thermocap",        "/v1/thermocap-multiple",   "thermocapMultiple", "Thermocap Multiple"),
    ("bg_exchange_reserve", "/v1/exchange-reserve-btc",  "exchangeReserveBtc","Exchange Reserve"),
    ("bg_exchange_netflow", "/v1/exchange-netflow-btc",  "exchangeNetflowBtc","Exchange Netflow"),
]

def try_download(filename, path, value_key, label):
    fpath = HIST_DIR / f"{filename}.json"
    if fpath.exists():
        existing = json.load(open(fpath))
        if isinstance(existing, list) and len(existing) > 500:
            return True  # already done

    url = f"https://bitcoin-data.com{path}"
    try:
        req = Request(url, headers={"User-Agent": "BTC-ReEntry-Backtest/1.0", "Accept": "application/json"})
        with urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
            if not raw.strip():
                return False
            data = json.loads(raw)
            if isinstance(data, dict) and data.get("error"):
                print(f"  ⏳ {label}: {data['error'].get('code', 'error')}")
                return False
            if isinstance(data, list) and len(data) > 0:
                points = []
                for item in data:
                    date = item.get("d") or item.get("theDay") or ""
                    value = item.get(value_key)
                    if date and value is not None:
                        try:
                            points.append({"date": date, "value": float(value)})
                        except:
                            pass
                points.sort(key=lambda x: x["date"])
                with open(fpath, "w") as f:
                    json.dump(points, f)
                print(f"  ✓ {label}: {len(points)} points ({points[0]['date']} → {points[-1]['date']})")
                return True
    except Exception as e:
        print(f"  ✗ {label}: {e}")
    return False


def main():
    max_attempts = 24  # 24 * 5min = 2 hours
    for attempt in range(max_attempts):
        remaining = []
        for ep in ENDPOINTS:
            if not (HIST_DIR / f"{ep[0]}.json").exists():
                remaining.append(ep)
            else:
                existing = json.load(open(HIST_DIR / f"{ep[0]}.json"))
                if not (isinstance(existing, list) and len(existing) > 500):
                    remaining.append(ep)

        if not remaining:
            print(f"\n✅ All {len(ENDPOINTS)} endpoints downloaded!")
            return True

        print(f"\nAttempt {attempt + 1}/{max_attempts} — {len(remaining)} remaining...")
        got_any = False
        for ep in remaining:
            success = try_download(*ep)
            if success:
                got_any = True
            time.sleep(8)

        remaining_after = sum(1 for ep in ENDPOINTS
                             if not (HIST_DIR / f"{ep[0]}.json").exists() or
                             not (isinstance(json.load(open(HIST_DIR / f"{ep[0]}.json")), list) and
                                  len(json.load(open(HIST_DIR / f"{ep[0]}.json"))) > 500)
                             if (HIST_DIR / f"{ep[0]}.json").exists())

        if remaining_after == 0:
            # Check once more cleanly
            all_done = all(
                (HIST_DIR / f"{ep[0]}.json").exists() and
                isinstance(json.load(open(HIST_DIR / f"{ep[0]}.json")), list) and
                len(json.load(open(HIST_DIR / f"{ep[0]}.json"))) > 500
                for ep in ENDPOINTS
            )
            if all_done:
                print(f"\n✅ All {len(ENDPOINTS)} endpoints downloaded!")
                return True

        if not got_any:
            print(f"  Server still down. Waiting 5 minutes before retry...")
            time.sleep(300)
        else:
            print(f"  Got some! Waiting 60s for rate limit reset...")
            time.sleep(60)

    print(f"\n⚠ Timed out after {max_attempts} attempts. Run again later.")
    return False


if __name__ == "__main__":
    main()
