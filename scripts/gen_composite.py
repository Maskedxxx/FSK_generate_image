"""
Тест Слоя 4: stitch + refine.

Использование:
    python scripts/gen_composite.py
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.layers.layer4_composite import render_composite

SCHEMA = "results/2026-04-01_5b1bdd01/L1_crops/schema_x2.png"
REFS_DIR = "scripts/debug_references"
ANALYSIS = "results/2026-04-01_5b1bdd01/L1_crops/analysis.json"
OUTPUT_DIR = "scripts/debug_composite"


def main():
    with open(ANALYSIS, "r", encoding="utf-8") as f:
        analysis = json.load(f)

    reference_paths = []
    rooms = []

    for room in analysis["rooms"]:
        name = room["name"] if room["name"] != "Nan" else f"room_{room['area']}m2"
        safe_name = name.replace(" ", "_").replace("/", "-")
        ref_path = os.path.join(REFS_DIR, f"{safe_name}.png")

        if os.path.exists(ref_path):
            reference_paths.append(ref_path)
            rooms.append(room)
            print(f"  {name} ({room['area']} м²)")
        else:
            print(f"  {name} — нет референса")

    print(f"\nКомнат: {len(rooms)}")
    print(f"Схема: {SCHEMA}\n")

    result = render_composite(SCHEMA, reference_paths, OUTPUT_DIR, rooms)
    print(f"\nГотово: {result}")


if __name__ == "__main__":
    main()
