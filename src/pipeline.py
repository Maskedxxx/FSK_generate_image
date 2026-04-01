"""
Оркестратор пайплайна генерации визуализаций.

Связывает все слои в единый процесс:
    Слой 1   → анализ планировки → JSON + crop'ы
    Слой 2   → генерация референса (двухпроходная: пустая комната → мебель)
    Слой 2.5 → описание артефактов по сторонам каждого референса
    Слой 3   → горизонтальные фото 4 сторон каждой комнаты

Структура результатов в output_dir (= results/{task_id}/):
    analysis.json           — результат Слоя 1
    L1_crops/               — вырезанные помещения (Слой 1)
    L2_references/          — референсы (вид сверху) + _empty промежуточные (Слой 2)
    L25_artifacts/          — JSON артефактов по сторонам (Слой 2.5)
    L3_renders/             — горизонтальные фото (Слой 3)

Функции:
    run_pipeline()       — полный пайплайн от схемы до результатов
    process_room()       — обработка одной комнаты (Слой 2 → 2.5 → 3)

Вызывается из:
    - src/api.py (фоновая задача через /generate)
"""

import os
import json
from typing import Callable

from .layers.layer1_analyze import analyze_floorplan
from .layers.layer2_generate import generate_room
from .layers.layer25_describe import describe_all_sides
from .layers.layer3_render import render_side
from .logger import get_logger

log = get_logger("fsk.pipeline")


def run_pipeline(
    image_path: str,
    answers: dict,
    output_dir: str,
    on_progress: Callable[[str], None] = None,
) -> dict:
    """
    Полный пайплайн: планировка + опросник → визуализации всех комнат.

    Принимает:
        image_path — путь к изображению планировки (JPG/PNG)
        answers — валидированные ответы опросника
        output_dir — папка задачи (results/{task_id}/)
        on_progress — колбэк для обновления прогресса (опционально)

    Выполняет:
        1. Слой 1: анализ планировки → analysis.json + crops/
        2. Для каждой комнаты: process_room()

    Возвращает:
        dict {rooms_count, rooms: [{name, area, shape, reference, sides}]}
    """
    os.makedirs(output_dir, exist_ok=True)

    def progress(msg: str) -> None:
        """Обновляет прогресс и логирует."""
        log.info(msg)
        if on_progress:
            on_progress(msg)

    # === Слой 1: анализ планировки ===
    progress("Слой 1: анализ планировки...")
    crops_dir = os.path.join(output_dir, "L1_crops")
    analysis = analyze_floorplan(image_path, output_dir=crops_dir)

    # Сохраняем analysis.json в L1_crops
    _save_json(os.path.join(crops_dir, "analysis.json"), analysis)
    rooms_count = len(analysis["rooms"])
    progress(f"Слой 1 готов: {rooms_count} помещений")

    # === Обработка каждой комнаты ===
    rooms_result = []

    for i, room in enumerate(analysis["rooms"]):
        room_name = room["name"] if room["name"] != "Nan" else f"room_{room['area']}m2"

        # Проверяем что crop есть
        if "crop_path" not in room:
            log.warning(f"[{room_name}] Нет crop — пропускаем")
            continue

        # Обрабатываем комнату (Слой 2 → 2.5 → 3)
        room_result = process_room(
            room=room,
            answers=answers,
            output_dir=output_dir,
            room_index=i,
            rooms_total=rooms_count,
            on_progress=on_progress,
        )
        rooms_result.append(room_result)

    progress(f"Готово: {len(rooms_result)} комнат обработано")

    return {
        "rooms_count": len(rooms_result),
        "rooms": rooms_result,
    }


def process_room(
    room: dict,
    answers: dict,
    output_dir: str,
    room_index: int = 0,
    rooms_total: int = 1,
    on_progress: Callable[[str], None] = None,
) -> dict:
    """
    Обработка одной комнаты: Слой 2 → Слой 2.5 → Слой 3.

    Принимает:
        room — метаданные комнаты из Слоя 1 {name, area, shape, crop_path}
        answers — валидированные ответы опросника
        output_dir — корневая папка задачи (results/{task_id}/)
        room_index — индекс комнаты (для прогресса)
        rooms_total — общее кол-во комнат (для прогресса)
        on_progress — колбэк для обновления прогресса

    Выполняет:
        Слой 2: crop → references/{name}.png (+ _empty.png промежуточный)
        Слой 2.5: references → artifacts/{name}.json
        Слой 3: references → renders/{name}_{side}.png

    Возвращает:
        dict {name, area, shape, reference, sides: {top, bottom, left, right}}
    """
    room_name = room["name"] if room["name"] != "Nan" else f"room_{room['area']}m2"
    safe_name = room_name.replace(" ", "_").replace("/", "-")
    counter = f"({room_index + 1}/{rooms_total})"

    def progress(msg: str) -> None:
        log.info(f"[{room_name}] {msg}")
        if on_progress:
            on_progress(msg)

    # === Слой 2: генерация референса (двухпроходная) ===
    progress(f"Слой 2: генерация {room_name} {counter}...")
    refs_dir = os.path.join(output_dir, "L2_references")
    os.makedirs(refs_dir, exist_ok=True)
    ref_path = os.path.join(refs_dir, f"{safe_name}.png")

    generate_room(room, answers, room["crop_path"], ref_path)
    log.info(f"[{room_name}] Слой 2: референс → {ref_path}")

    # === Слой 2.5: описание артефактов по сторонам ===
    progress(f"Слой 2.5: артефакты {room_name} {counter}...")
    artifacts_dir = os.path.join(output_dir, "L25_artifacts", safe_name)
    sides_artifacts = describe_all_sides(ref_path, room, artifacts_dir)

    # Сохраняем артефакты
    _save_json(os.path.join(output_dir, "L25_artifacts", f"{safe_name}.json"), sides_artifacts)
    log.info(f"[{room_name}] Слой 2.5: артефакты описаны")

    # === Слой 3: горизонтальные фото для каждой стороны ===
    sides_result = {}
    renders_dir = os.path.join(output_dir, "L3_renders")
    os.makedirs(renders_dir, exist_ok=True)

    for side in ["top", "bottom", "left", "right"]:
        progress(f"Слой 3: {room_name} → {side} {counter}...")
        side_path = os.path.join(renders_dir, f"{safe_name}_{side}.png")
        artifacts = sides_artifacts.get(side, [])

        try:
            render_side(ref_path, side_path, side, artifacts)
            sides_result[side] = side_path
            log.info(f"[{room_name}] Слой 3: {side} готов")
        except Exception as e:
            sides_result[side] = f"error: {str(e)}"
            log.error(f"[{room_name}] Слой 3: {side} ОШИБКА — {e}")

    return {
        "name": room_name,
        "area": room["area"],
        "shape": room["shape"],
        "reference": ref_path,
        "sides": sides_result,
    }


# === УТИЛИТЫ ===


def _save_json(path: str, data: dict) -> None:
    """Сохраняет dict в JSON файл."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
