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

print("→ Pushing to GitHub Pages...")
r3 = subprocess.run(["git", "add", "index.html", "data/indicators.json"],
                    cwd=PROJECT)
if r3.returncode == 0:
    r4 = subprocess.run(["git", "commit", "-m", "Auto-update dashboard data"],
                        cwd=PROJECT)
    if r4.returncode == 0:
        r5 = subprocess.run(["git", "push"], cwd=PROJECT)
        if r5.returncode == 0:
            print("✓ Pushed to GitHub Pages")
        else:
            print(f"✗ git push failed (exit {r5.returncode})")
    else:
        print("→ No changes to commit (data unchanged)")
else:
    print(f"✗ git add failed (exit {r3.returncode})")

print("=== Build complete ===")
