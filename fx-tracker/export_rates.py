#!/usr/bin/env python3
"""
export_rates.py — Export latest rates from SQLite to rates.json
Run after each poll cycle to keep the static site live.
Called from bot.py after every successful rate save.
"""
import json
import os
import sys
from datetime import datetime

# Add parent dir so db is importable when run standalone
sys.path.insert(0, os.path.dirname(__file__))
import db

# Currency pairs to export
PAIRS = [
    ("USD", "NGN"),
    ("GBP", "NGN"),
    ("EUR", "NGN"),
    ("USD", "GHS"),
    ("USD", "KES"),
    ("USD", "ZAR"),
]

COUNTRY_META = {
    "NGN": {"flag": "🇳🇬", "country": "Nigeria",      "sym": "₦",   "parallel_label": "Parallel market"},
    "GHS": {"flag": "🇬🇭", "country": "Ghana",        "sym": "GH₵", "parallel_label": "Street/Market"},
    "KES": {"flag": "🇰🇪", "country": "Kenya",        "sym": "KSh", "parallel_label": "Market rate"},
    "ZAR": {"flag": "🇿🇦", "country": "South Africa", "sym": "R",   "parallel_label": "Market rate"},
}

def export():
    rates = {}
    for foreign, local in PAIRS:
        r = db.get_latest_rate(foreign, local)
        if not r:
            continue
        meta = COUNTRY_META.get(local, {})
        spread = r.get("parallel_rate", 0) - r.get("cbn_rate", 0)
        spread_pct = (spread / r["cbn_rate"] * 100) if r.get("cbn_rate") else 0
        key = f"{foreign}_{local}"
        rates[key] = {
            "foreign":       foreign,
            "local":         local,
            "flag":          meta.get("flag", ""),
            "country":       meta.get("country", local),
            "sym":           meta.get("sym", ""),
            "parallel_label": meta.get("parallel_label", "Market"),
            "parallel_rate": r.get("parallel_rate"),
            "cbn_rate":      r.get("cbn_rate"),
            "spread":        round(spread, 2),
            "spread_pct":    round(spread_pct, 2),
            "fetched_at":    r.get("fetched_at", "")[:16],
        }

    output = {
        "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rates": rates,
    }

    # Write to the parallelrate repo
    out_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "tmp", "parallelrate", "rates.json")
    out_path = os.path.normpath(out_path)

    # Also write next to this script for fallback
    local_path = os.path.join(os.path.dirname(__file__), "rates.json")

    for path in [local_path]:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"Exported {len(rates)} rate pairs to {path}")

    return output

if __name__ == "__main__":
    result = export()
    print(json.dumps(result, indent=2))
