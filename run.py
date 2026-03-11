#!/usr/bin/env python3
"""
Runner script for LaunchAgent — replaces build.sh
Avoids /bin/bash FDA issues on macOS.
"""
import subprocess, sys, os

PROJECT = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(PROJECT, "scripts")

print("=== Bitcoin Re-Entry Dashboard Builder ===")

print("→ Fetching data...")
r1 = subprocess.run([sys.executable, os.path.join(SCRIPTS, "fetch-data.py")],
                    cwd=PROJECT)
if r1.returncode != 0:
    print(f"✗ fetch-data.py failed (exit {r1.returncode})")
    sys.exit(1)

print("→ Building dashboard...")
r2 = subprocess.run([sys.executable, os.path.join(SCRIPTS, "build-html.py")],
                    cwd=PROJECT)
if r2.returncode != 0:
    print(f"✗ build-html.py failed (exit {r2.returncode})")
    sys.exit(1)

print("=== Build complete ===")
