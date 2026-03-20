# Оркестратор пайплайна: Слой 1 → Слой 2 по каждой комнате

import os
import json
from .layers.analyze import analyze_floorplan
from .layers.generate import generate_room
from .questionnaire import validate_answers


def run_pipeline(image_path: str, answers: dict, output_dir: str) -> dict:
    """
    Полный пайплайн: планировка + опросник → визуализации всех комнат.

    Аргументы:
        image_path: путь к изображению планировки
        answers: ответы опросника {style, colors, materials, ...}
        output_dir: папка для сохранения результатов

    Возвращает:
        dict с результатами: analysis, rooms с путями к картинкам
    """
    os.makedirs(output_dir, exist_ok=True)

    # Валидируем ответы опросника
    validated = validate_answers(answers)

    # Слой 1: анализ планировки
    print("[Слой 1] Анализ планировки...")
    analysis = analyze_floorplan(image_path)

    # Сохраняем JSON анализа
    analysis_path = os.path.join(output_dir, "analysis.json")
    with open(analysis_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)
    print(f"[Слой 1] Найдено помещений: {len(analysis['rooms'])}")

    # Слой 2: генерация визуализации для каждой комнаты
    results = []
    for i, room in enumerate(analysis["rooms"]):
        room_label = room["name"] if room["name"] != "Nan" else f"room_{room['area']}m2"
        safe_name = room_label.replace(" ", "_").replace("/", "-")
        output_path = os.path.join(output_dir, f"{i+1}_{safe_name}.png")

        print(f"[Слой 2] Генерация: {room_label} ({room['area']} м²)...")
        generate_room(room, validated, image_path, output_path)

        results.append({
            "room": room,
            "image_path": output_path,
        })
        print(f"[Слой 2] Сохранено: {output_path}")

    return {
        "analysis": analysis,
        "rooms": results,
    }
