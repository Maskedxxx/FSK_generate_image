"""
Слой 2: Генерация референса (вид сверху).

Двухпроходная генерация через OSMI-ноды:
    Проход 1: crop → FSK_Layer2_ImageGen → пустая комната
    Проход 2: пустая комната + crop → FSK_Layer2_ImageGen_Dual → референс с мебелью

Функции:
    generate_room()         — основная: crop + опросник → PNG референс
    _upscale_and_encode()   — масштабирование crop'а до 1024px + base64
"""

import base64
import io
import os
import math
from PIL import Image

from ..prompts import build_layer2_prompt, LAYER2_PASS1_SYSTEM, LAYER2_PASS1_USER, LAYER2_PASS2_SYSTEM
from ..osmi_client import call_osmi_image, call_osmi_image_dual
from ..logger import get_logger

log = get_logger("fsk.layer2")

# Минимальный размер длинной стороны для отправки
MIN_LONG_SIDE = 1024


def generate_room(room: dict, answers: dict, crop_path: str, output_path: str) -> str:
    """
    Генерирует фотореалистичный референс комнаты (вид сверху).
    Двухпроходная генерация через OSMI-ноды.

    Принимает:
        room — метаданные комнаты из Слоя 1 {name, area, shape, crop_path}
        answers — валидированные ответы опросника
        crop_path — путь к вырезанному изображению помещения
        output_path — путь для сохранения PNG

    Выполняет:
        Проход 1: crop → OSMI (1 изображение) → пустая комната
        Проход 2: пустая комната + crop → OSMI (2 изображения) → референс с мебелью

    Возвращает:
        путь к сохранённому изображению
    """
    room_name = room.get("name", "unknown")

    # Проверяем что crop существует
    if not os.path.exists(crop_path):
        raise FileNotFoundError(f"Crop файл не найден: {crop_path}")

    log.info(f"[{room_name}] Генерация референса: {room.get('area', '?')} м², {room.get('shape', '?')}")

    # Масштабируем crop
    crop_base64 = _upscale_and_encode(crop_path, room_name)

    # Расчёт размеров для промпта
    room_width, room_height = 0.0, 0.0
    try:
        img = Image.open(crop_path)
        w, h = img.size
        ratio = w / h
        area_boosted = room.get("area", 10) * 1.1
        room_height = math.sqrt(area_boosted / ratio)
        room_width = ratio * room_height
    except Exception:
        pass

    # === ПРОХОД 1: Пустая комната ===
    log.info(f"[{room_name}] Проход 1: пустая комната...")
    pass1_user = LAYER2_PASS1_USER.format(
        room_name=room_name,
        room_area=room.get("area", 0),
        room_width=f"{room_width:.1f}",
        room_height=f"{room_height:.1f}",
        room_shape=room.get("shape", "прямоугольная"),
    )
    # Через OSMI-ноду FSK_Layer2_ImageGen (1 изображение)
    pass1_prompt = f"{LAYER2_PASS1_SYSTEM}\n\n{pass1_user}"
    empty_room_b64 = call_osmi_image(pass1_prompt, crop_base64, f"{room_name}/pass1")

    # Сохраняем пустую комнату как промежуточный артефакт
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    empty_path = output_path.replace(".png", "_empty.png")
    with open(empty_path, "wb") as f:
        f.write(base64.b64decode(empty_room_b64))
    log.info(f"[{room_name}] Проход 1 готов: {empty_path}")

    # === ПРОХОД 2: Наполнение мебелью ===
    log.info(f"[{room_name}] Проход 2: наполнение мебелью...")
    # Через OSMI-ноду FSK_Layer2_ImageGen_Dual (2 изображения)
    _, pass2_user = build_layer2_prompt(room, answers)
    pass2_prompt = f"{LAYER2_PASS2_SYSTEM}\n\n{pass2_user}"
    reference_b64 = call_osmi_image_dual(pass2_prompt, empty_room_b64, crop_base64, f"{room_name}/pass2")

    # Сохраняем финальный референс
    img_bytes = base64.b64decode(reference_b64)
    with open(output_path, "wb") as f:
        f.write(img_bytes)

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
