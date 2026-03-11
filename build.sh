#!/bin/bash
set -e

echo "=== Bitcoin Re-Entry Dashboard Builder ==="

# Always fetch — the smart cache in fetch-data.py handles freshness per endpoint
echo "→ Fetching data (cache handles per-endpoint freshness)..."
python3 scripts/fetch-data.py

echo "→ Building dashboard..."
python3 scripts/build-html.py

echo "=== Build complete → index.html ==="
echo "Open index.html in your browser to view the dashboard"
