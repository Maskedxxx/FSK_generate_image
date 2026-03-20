# Тест Слоя 2: генерация визуализации одной комнаты
# Запуск: python -m tests.test_layer2 "Кухня-гостиная"
# Или по индексу: python -m tests.test_layer2 0

import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.layers.generate import generate_room
from src.questionnaire import TEST_ANSWERS, validate_answers
from src.prompts import build_layer2_prompt

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")


def find_latest_layer1():
    """Находит последнюю сессию Слоя 1 (только директории)."""
    dirs = [d for d in os.listdir(RESULTS_DIR) if d.startswith("layer1_") and os.path.isdir(os.path.join(RESULTS_DIR, d))]
    if not dirs:
        return None
    dirs.sort()
    return os.path.join(RESULTS_DIR, dirs[-1])


def main():
    # Находим последний анализ
    layer1_dir = find_latest_layer1()
    if not layer1_dir:
        print("Нет результатов Слоя 1. Запустите: python -m tests.test_layer1")
        return

    analysis_path = os.path.join(layer1_dir, "analysis.json")
    with open(analysis_path, "r", encoding="utf-8") as f:
        analysis = json.load(f)

    rooms = analysis["rooms"]

    # Без аргумента — показываем список
    if len(sys.argv) < 2:
        print(f"Сессия Слоя 1: {layer1_dir}")
        print("Доступные помещения:")
        for i, r in enumerate(rooms):
            name = r["name"] if r["name"] != "Nan" else "(без имени)"
            has_crop = "crop_path" in r
            print(f"  [{i}] {name} — {r['area']} м², {r['shape']} {'✅ crop' if has_crop else '❌ no crop'}")
        print(f"\nЗапуск: python -m tests.test_layer2 <индекс или название>")
        return

    arg = sys.argv[1]

    # Ищем по индексу или по названию
    room = None
    if arg.isdigit():
        idx = int(arg)
        if 0 <= idx < len(rooms):
            room = rooms[idx]
    else:
        for r in rooms:
            if arg.lower() in r["name"].lower():
                room = r
                break

    if not room:
        print(f"Помещение '{arg}' не найдено")
        return

    if "crop_path" not in room:
        print(f"Нет вырезанного изображения для этой комнаты")
        return

    room_label = room["name"] if room["name"] != "Nan" else f"room_{room['area']}m2"
    print(f"Генерация: {room_label} ({room['area']} м², {room['shape']})")
    print(f"Crop: {room['crop_path']}")

    # Валидируем ответы
    validated = validate_answers(TEST_ANSWERS)

    # Показываем промпт
    system_prompt, user_prompt = build_layer2_prompt(room, validated)
    print(f"\n=== SYSTEM PROMPT ===\n{system_prompt if system_prompt else '(пустой)'}")
    print(f"\n=== USER PROMPT ===\n{user_prompt}\n")

    # Подпапка сессии
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = os.path.join(RESULTS_DIR, f"layer2_{session_id}")
    os.makedirs(session_dir, exist_ok=True)

    safe_name = room_label.replace(" ", "_").replace("/", "-")
    output_path = os.path.join(session_dir, f"{safe_name}.png")

    print("Генерация изображения...")
    generate_room(room, validated, room["crop_path"], output_path)
    print(f"Сохранено: {output_path}")


if __name__ == "__main__":
    main()
