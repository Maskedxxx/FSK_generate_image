"""
Оркестратор пайплайна генерации визуализаций.

Связывает все слои в единый процесс:
    Слой 1 → анализ планировки → JSON + crop'ы
    Слой 2 → генерация референса сверху с мебелью (1 проход)
    Слой 3 → рендер из 2 угловых ракурсов (30° и 222°)
    Слой 4 → общий рендер всей квартиры сверху

Структура результатов в output_dir (= results/{task_id}/):
    L1_crops/               — анализ + кропы помещений (Слой 1)
    L2_references/          — референсы вид сверху (Слой 2)
    L3_renders/             — фото из угловых ракурсов (Слой 3)
    L4_composite/           — общий рендер квартиры (Слой 4)

Функции:
    run_pipeline()       — полный пайплайн от схемы до результатов
    process_room()       — обработка одной комнаты (Слой 2 → 3)

Вызывается из:
    - src/api.py (фоновая задача через /generate)
"""

import os
import json
from typing import Callable

from .layers.layer1_analyze import analyze_floorplan
from .layers.layer2_generate import generate_room
from .layers.layer3_render import render_angles
from .layers.layer4_composite import render_composite
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
        dict {rooms_count, rooms: [...], composite: path}
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

    # === Обработка каждой комнаты (Слой 2 → 3) ===
    rooms_result = []
    reference_paths = []

    for i, room in enumerate(analysis["rooms"]):
        room_name = room["name"] if room["name"] != "Nan" else f"room_{room['area']}m2"

        if "crop_path" not in room:
            log.warning(f"[{room_name}] Нет crop — пропускаем")
            continue

        room_result = process_room(
            room=room,
            answers=answers,
            output_dir=output_dir,
            room_index=i,
            rooms_total=rooms_count,
            on_progress=on_progress,
        )
        rooms_result.append(room_result)
        reference_paths.append(room_result["reference"])

    # === Слой 4: общий рендер квартиры ===
    composite_path = None
    if reference_paths:
        progress("Слой 4: общий рендер квартиры...")
        schema_path = os.path.join(crops_dir, "schema_x2.png")
        composite_dir = os.path.join(output_dir, "L4_composite")
        try:
            composite_path = render_composite(schema_path, reference_paths, composite_dir)
            progress("Слой 4 готов")
        except Exception as e:
            log.error(f"Слой 4 ОШИБКА: {e}")

    progress(f"Готово: {len(rooms_result)} комнат обработано")

    return {
        "rooms_count": len(rooms_result),
        "rooms": rooms_result,
        "composite": composite_path,
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
    Обработка одной комнаты: Слой 2 → Слой 3.

    Принимает:
        room — метаданные комнаты из Слоя 1 {name, area, shape, crop_path}
        answers — валидированные ответы опросника
        output_dir — корневая папка задачи (results/{task_id}/)
        room_index — индекс комнаты (для прогресса)
        rooms_total — общее кол-во комнат (для прогресса)
        on_progress — колбэк для обновления прогресса

    Выполняет:
        Слой 2: crop → L2_references/{name}.png
        Слой 3: референс → L3_renders/{name}_angle30.png, {name}_angle222.png

    Возвращает:
        dict {name, area, shape, reference, angles: {30: path, 222: path}}
    """
    room_name = room["name"] if room["name"] != "Nan" else f"room_{room['area']}m2"
    safe_name = room_name.replace(" ", "_").replace("/", "-")
    counter = f"({room_index + 1}/{rooms_total})"

    def progress(msg: str) -> None:
        log.info(f"[{room_name}] {msg}")
        if on_progress:
            on_progress(msg)

    # === Слой 2: генерация референса (1 проход) ===
    progress(f"Слой 2: генерация {room_name} {counter}...")
    refs_dir = os.path.join(output_dir, "L2_references")
    os.makedirs(refs_dir, exist_ok=True)
    ref_path = os.path.join(refs_dir, f"{safe_name}.png")

    generate_room(room, answers, room["crop_path"], ref_path)
    log.info(f"[{room_name}] Слой 2: референс → {ref_path}")

    # === Слой 3: рендер из 2 угловых ракурсов ===
    progress(f"Слой 3: рендер углов {room_name} {counter}...")
    renders_dir = os.path.join(output_dir, "L3_renders")
    room_analysis = room.get("analysis", "")

    render_result = {}
    try:
        render_result = render_angles(ref_path, renders_dir, room_name, room_analysis)
        log.info(f"[{room_name}] Слой 3: 2 ракурса готово")
    except Exception as e:
        log.error(f"[{room_name}] Слой 3 ОШИБКА: {e}")

    return {
        "name": room_name,
        "area": room["area"],
        "shape": room["shape"],
        "reference": ref_path,
        "renders": render_result,
    }


# === УТИЛИТЫ ===


def _save_json(path: str, data: dict) -> None:
    """Сохраняет dict в JSON файл."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
