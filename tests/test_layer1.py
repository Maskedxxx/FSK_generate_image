# Тест Слоя 1: анализ планировки + нарезка комнат
# Запуск: python -m tests.test_layer1

import json
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.layers.analyze import analyze_floorplan

# Путь к тестовой планировке
IMAGE_PATH = "/Users/mask/Downloads/конеткст_для_агента/Валидные/Снимок экрана 2026-03-10 130313.jpg"
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")


def main():
    # Подпапка сессии по времени
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = os.path.join(RESULTS_DIR, f"layer1_{session_id}")
    os.makedirs(session_dir, exist_ok=True)

    print(f"=== Слой 1: анализ + нарезка ===")
    print(f"Сессия: {session_dir}")
    print()

    # Анализ с нарезкой
    result = analyze_floorplan(IMAGE_PATH, output_dir=session_dir)

    # Сохраняем JSON
    json_path = os.path.join(session_dir, "analysis.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # Выводим результат
    rooms = result.get("rooms", [])
    print(f"Помещений: {len(rooms)}")
    print()

    for i, room in enumerate(rooms):
        name = room["name"] if room["name"] != "Nan" else "(без имени)"
        bbox = room.get("bbox", {})
        crop = room.get("crop_path", "нет")
        print(f"  [{i}] {name} — {room['area']} м², {room['shape']}")
        print(f"      bbox: x={bbox.get('x')}%, y={bbox.get('y')}%, w={bbox.get('w')}%, h={bbox.get('h')}%")
        print(f"      crop: {crop}")
        print()

    print(f"JSON: {json_path}")
    print(f"Папка: {session_dir}")


if __name__ == "__main__":
    main()
