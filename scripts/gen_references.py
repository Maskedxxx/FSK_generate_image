"""
Скрипт генерации референсов из готовых кропов.

Использование:
    python scripts/gen_references.py

Берёт кропы из results/2026-04-01_5b1bdd01/L1_crops/
Результаты в scripts/debug_references/
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.layers.layer2_generate import generate_room

CROPS_DIR = "results/2026-04-01_5b1bdd01/L1_crops"
ANALYSIS_PATH = os.path.join(CROPS_DIR, "analysis.json")
OUTPUT_DIR = "scripts/debug_references"

# Ответы опросника
ANSWERS = {
    "style": "Скандинавский",
    "colors": "Светлые (белый, беж, серый)",
    "materials": ["Натуральное дерево"],
    "residents": "2 взрослых без детей",
    "work_from_home": "Нет, работа вне дома",
    "hobby": "Чтение и коллекционирование (полки, библиотека, кресло)",
    "bathroom_layout": "Совмещённый санузел",
    "bath_type": "Душевая",
    "storage": ["Чемоданы"],
}


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(ANALYSIS_PATH, "r", encoding="utf-8") as f:
        analysis = json.load(f)

    rooms = analysis["rooms"]
    print(f"Комнат: {len(rooms)}\n")

    for i, room in enumerate(rooms):
        name = room["name"] if room["name"] != "Nan" else f"room_{room['area']}m2"
        safe_name = name.replace(" ", "_").replace("/", "-")

        # Ищем crop файл
        crop_path = None
        for fname in os.listdir(CROPS_DIR):
            if fname.endswith("_crop.png") and safe_name in fname:
                crop_path = os.path.join(CROPS_DIR, fname)
                break

        if not crop_path:
            # Пробуем по номеру
            expected = f"{i + 1}_{safe_name}_crop.png"
            candidate = os.path.join(CROPS_DIR, expected)
            if os.path.exists(candidate):
                crop_path = candidate

        if not crop_path:
            print(f"[{name}] Кроп не найден — пропускаем")
            continue

        output_path = os.path.join(OUTPUT_DIR, f"{safe_name}.png")
        print(f"[{i+1}/{len(rooms)}] {name} | crop: {os.path.basename(crop_path)}")

        try:
            generate_room(room, ANSWERS, crop_path, output_path)
            print(f"  → {output_path}")
        except Exception as e:
            print(f"  ✗ Ошибка: {e}")

    print(f"\nГотово. Результаты в {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
