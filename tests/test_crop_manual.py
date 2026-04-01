"""
Ручной тест кропа по полигонам.

Использование:
    python tests/test_crop_manual.py <image_path> <coordinates_json>

Пример:
    python tests/test_crop_manual.py results/2026-03-31_abc123/L1_crops/schema_x2.png results/2026-03-31_abc123/L1_crops/analysis.json

Результаты сохраняются в tests/test_crop_results/
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.layers.layer1_analyze import _crop_rooms

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_crop_results")


def main():
    if len(sys.argv) < 3:
        print("Использование: python tests/test_crop_manual.py <image_path> <coordinates_json>")
        sys.exit(1)

    image_path = sys.argv[1]
    json_path = sys.argv[2]

    if not os.path.exists(image_path):
        print(f"Файл не найден: {image_path}")
        sys.exit(1)
    if not os.path.exists(json_path):
        print(f"Файл не найден: {json_path}")
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        analysis = json.load(f)

    rooms = analysis.get("rooms", [])
    print(f"Изображение: {image_path}")
    print(f"Комнат в JSON: {len(rooms)}")

    # Очищаем выходную папку
    os.makedirs(OUT_DIR, exist_ok=True)

    # Кропаем
    result = _crop_rooms(image_path, analysis, OUT_DIR)

    # Итог
    cropped = sum(1 for r in result["rooms"] if "crop_path" in r)
    skipped = result.get("skipped_rooms", [])
    print(f"\nГотово: {cropped} кропов в {OUT_DIR}")
    if skipped:
        print(f"Пропущено: {len(skipped)}")
        for s in skipped:
            print(f"  - {s['name']}: {s['reason']}")


if __name__ == "__main__":
    main()
