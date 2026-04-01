"""
Слой 2: Генерация референса (вид сверху).

Однопроходная генерация через OSMI: crop → FSK_Layer2_ImageGen → референс с мебелью.

Функции:
    generate_room()         — основная: crop + опросник → PNG референс
    _upscale_and_encode()   — масштабирование crop'а до 1024px + base64
"""

import base64
import io
import json
import os
import math
import time
from datetime import datetime, timezone
from PIL import Image

from ..prompts import build_layer2_prompt, LAYER2_SYSTEM_PROMPT
from ..osmi_client import call_osmi_image
from ..logger import get_logger

log = get_logger("fsk.layer2")

# Минимальный размер длинной стороны для отправки
MIN_LONG_SIDE = 1024


def generate_room(room: dict, answers: dict, crop_path: str, output_path: str) -> str:
    """
    Генерирует фотореалистичный референс комнаты (вид сверху).
    Однопроходная генерация: crop → OSMI → референс сразу с мебелью.

    Принимает:
        room — метаданные комнаты из Слоя 1 {name, area, shape, crop_path}
        answers — валидированные ответы опросника
        crop_path — путь к вырезанному изображению помещения
        output_path — путь для сохранения PNG

    Возвращает:
        путь к сохранённому изображению
    """
    room_name = room.get("name", "unknown")

    if not os.path.exists(crop_path):
        raise FileNotFoundError(f"Crop файл не найден: {crop_path}")

    log.info(f"[{room_name}] Генерация референса: {room.get('area', '?')} м², {room.get('shape', '?')}")

    # Масштабируем crop
    crop_base64 = _upscale_and_encode(crop_path, room_name)

    # Собираем промпт с опросником
    _, user_prompt = build_layer2_prompt(room, answers)
    prompt = f"{LAYER2_SYSTEM_PROMPT}\n\n{user_prompt}"

    # Отправляем в OSMI
    t_start = time.monotonic()
    reference_b64 = call_osmi_image(prompt, crop_base64, f"{room_name}/generate")
    osmi_sec = round(time.monotonic() - t_start, 2)

    # Сохраняем референс
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img_bytes = base64.b64decode(reference_b64)
    with open(output_path, "wb") as f:
        f.write(img_bytes)

    # Сохраняем мету
    meta = {
        "layer": 2,
        "room": room_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt": prompt,
        "timing": {"osmi_call_sec": osmi_sec},
        "output_kb": len(img_bytes) // 1024,
    }
    meta_path = output_path.replace(".png", "_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    log.info(f"[{room_name}] Референс сохранён: {output_path} ({len(img_bytes) // 1024} KB)")
    return output_path


# === ВНУТРЕННИЕ ФУНКЦИИ ===


def _upscale_and_encode(image_path: str, room_name: str = "") -> str:
    """
    Масштабирует изображение если оно меньше MIN_LONG_SIDE и кодирует в base64.

    Принимает:
        image_path — путь к файлу
        room_name — для логирования

    Возвращает:
        base64-строка PNG
    """
    try:
        img = Image.open(image_path)
    except Exception as e:
        raise ValueError(f"Не удалось открыть изображение {image_path}: {e}")

    w, h = img.size
    long_side = max(w, h)

    if long_side < MIN_LONG_SIDE:
        scale = MIN_LONG_SIDE / long_side
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        log.info(f"[{room_name}] Масштабирование: {w}x{h} → {new_w}x{new_h}")
    else:
        log.info(f"[{room_name}] Размер crop: {w}x{h} (масштабирование не требуется)")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")
