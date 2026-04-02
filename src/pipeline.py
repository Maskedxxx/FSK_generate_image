"""
Оркестратор пайплайна генерации визуализаций.

Слои работают с локальным temp. После каждого слоя — upload в хранилище (S3/local).

    Слой 1 → анализ планировки → JSON + crop'ы → upload L1_crops/
    Слой 2 → генерация референса с мебелью → upload L2_references/
    Слой 3 → рендер с 2 сторон → upload L3_renders/
    Слой 4 → общий рендер квартиры → upload L4_composite/

Функции:
    run_pipeline()       — полный пайплайн от схемы до результатов
    process_room()       — обработка одной комнаты (Слой 2 → 3)

Вызывается из:
    - src/api.py (фоновая задача через /generate)
"""

import os
import json
import shutil
import tempfile
from typing import Callable

from .layers.layer1_analyze import analyze_floorplan
from .layers.layer2_generate import generate_room
from .layers.layer3_render import render_angles
from .layers.layer4_composite import render_composite
from .storage import StorageBackend, create_storage
from .logger import get_logger

log = get_logger("fsk.pipeline")


def run_pipeline(
    task_id: str,
    image_path: str,
    answers: dict,
    storage: StorageBackend = None,
    on_progress: Callable[[str], None] = None,
) -> dict:
    """
    Полный пайплайн: планировка + опросник → визуализации всех комнат.
    Слои работают с temp-директорией, результаты загружаются в storage.

    Принимает:
        task_id — идентификатор задачи
        image_path — путь к изображению планировки (JPG/PNG)
        answers — валидированные ответы опросника
        storage — хранилище (S3/local), если None — создаётся по конфигу
        on_progress — колбэк для обновления прогресса (опционально)

    Возвращает:
        dict {rooms_count, rooms: [...], composite: key}
    """
    if storage is None:
        storage = create_storage()

    # Temp-директория для работы слоёв
    tmp_dir = tempfile.mkdtemp(prefix=f"fsk_{task_id}_")
    log.info(f"Рабочая директория: {tmp_dir}")

    def progress(msg: str) -> None:
        log.info(msg)
        if on_progress:
            on_progress(msg)

    try:
        # === Слой 1: анализ планировки ===
        progress("Слой 1: анализ планировки...")
        crops_dir = os.path.join(tmp_dir, "L1_crops")
        analysis = analyze_floorplan(image_path, output_dir=crops_dir)

        # Сохраняем analysis.json
        _save_json(os.path.join(crops_dir, "analysis.json"), analysis)
        rooms_count = len(analysis["rooms"])

        # Upload L1_crops в хранилище
        _upload_dir(storage, task_id, "L1_crops", crops_dir)

        # Переписываем crop_path на ключи хранилища (для Слоя 2)
        for room in analysis.get("rooms", []):
            if "crop_path" in room:
                rel = os.path.relpath(room["crop_path"], tmp_dir)
                room["crop_path"] = f"{task_id}/{rel}"
        # Перезаписываем analysis.json с корректными путями
        storage.write_json(f"{task_id}/L1_crops/analysis.json", analysis)

        progress(f"Слой 1 готов: {rooms_count} помещений")

        # === Обработка каждой комнаты (Слой 2 → 3) ===
        rooms_result = []
        reference_paths = []

        for i, room in enumerate(analysis["rooms"]):
            room_name = room["name"] if room["name"] != "Nan" else f"room_{room['area']}m2"

            if "crop_path" not in room:
                log.warning(f"[{room_name}] Нет crop — пропускаем")
                continue

            # Если crop_path — ключ S3, скачиваем в temp
            crop_path = room["crop_path"]
            if not os.path.exists(crop_path):
                local_crop = os.path.join(tmp_dir, "L1_crops", os.path.basename(crop_path))
                os.makedirs(os.path.dirname(local_crop), exist_ok=True)
                crop_data = storage.read_bytes(crop_path)
                with open(local_crop, "wb") as f:
                    f.write(crop_data)
                room["crop_path"] = local_crop

            room_result = process_room(
                room=room,
                answers=answers,
                output_dir=tmp_dir,
                room_index=i,
                rooms_total=rooms_count,
                on_progress=on_progress,
            )
            rooms_result.append(room_result)
            reference_paths.append(room_result["reference"])

        # Upload L2_references и L3_renders
        refs_dir = os.path.join(tmp_dir, "L2_references")
        renders_dir = os.path.join(tmp_dir, "L3_renders")
        if os.path.exists(refs_dir):
            _upload_dir(storage, task_id, "L2_references", refs_dir)
        if os.path.exists(renders_dir):
            _upload_dir(storage, task_id, "L3_renders", renders_dir)

        # === Слой 4: общий рендер квартиры ===
        composite_key = None
        if reference_paths:
            progress("Слой 4: общий рендер квартиры...")
            schema_path = os.path.join(crops_dir, "schema_x2.png")
            composite_dir = os.path.join(tmp_dir, "L4_composite")
            try:
                render_composite(schema_path, reference_paths, composite_dir)
                _upload_dir(storage, task_id, "L4_composite", composite_dir)
                composite_key = f"{task_id}/L4_composite/composite.png"
                progress("Слой 4 готов")
            except Exception as e:
                log.error(f"Слой 4 ОШИБКА: {e}")

        progress(f"Готово: {len(rooms_result)} комнат обработано")

        # Формируем результат с ключами хранилища (не локальными путями)
        for room_res in rooms_result:
            safe = room_res["name"].replace(" ", "_").replace("/", "-")
            room_res["reference"] = f"{task_id}/L2_references/{safe}.png"
            if "renders" in room_res:
                for side_key, local_path in room_res["renders"].items():
                    fname = os.path.basename(local_path)
                    room_res["renders"][side_key] = f"{task_id}/L3_renders/{fname}"

        return {
            "rooms_count": len(rooms_result),
            "rooms": rooms_result,
            "composite": composite_key,
        }

    finally:
        # Очистка temp-директории
        shutil.rmtree(tmp_dir, ignore_errors=True)
        log.info(f"Temp очищен: {tmp_dir}")


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


def _upload_dir(storage: StorageBackend, task_id: str, prefix: str, local_dir: str) -> None:
    """Загружает все файлы из локальной папки в хранилище."""
    if not os.path.exists(local_dir):
        return
    count = 0
    for root, dirs, files in os.walk(local_dir):
        for fname in files:
            local_path = os.path.join(root, fname)
            rel = os.path.relpath(local_path, local_dir)
            key = f"{task_id}/{prefix}/{rel}"
            with open(local_path, "rb") as f:
                storage.write_bytes(key, f.read())
            count += 1
    log.info(f"Upload {prefix}: {count} файлов → {task_id}/{prefix}/")
