"""
Слой 3: Рендер комнаты из угловых ракурсов.

Берёт референс (вид сверху из Слоя 2), поворачивает на заданный угол,
отправляет через OSMI → получает фото на уровне глаз из угла.

Два ракурса: 30° и 222° (противоположные углы).

Функции:
    render_angles()     — основная: референс → 2 фото из углов
    render_angle()      — рендер одного угла
"""

import base64
import io
import json
import os
import time
from datetime import datetime, timezone
from PIL import Image

from ..prompts import LAYER3_ANGLE_PROMPT
from ..osmi_client import call_osmi_image
from ..logger import get_logger

log = get_logger("fsk.layer3")

# Размер для апскейла референса перед отправкой
REF_MIN_SIZE = 2000


def render_angles(reference_path: str, output_dir: str, room_name: str, room_analysis: str = "") -> dict:
    """
    Генерирует 2 фото: с ближней и дальней стороны.
    Рендер 1: референс как есть (съёмка снизу вверх).
    Рендер 2: референс повёрнут на 180° (съёмка с противоположной стороны).
    Горизонтальные референсы сначала поворачиваются на 90° → все вертикальные.

    Принимает:
        reference_path — путь к референсу из Слоя 2 (вид сверху)
        output_dir — папка для сохранения
        room_name — имя комнаты
        room_analysis — анализ комнаты из Слоя 1

    Возвращает:
        dict {"side_a": path, "side_b": path}
    """
    if not os.path.exists(reference_path):
        raise FileNotFoundError(f"Референс не найден: {reference_path}")

    os.makedirs(output_dir, exist_ok=True)
    safe_name = room_name.replace(" ", "_").replace("/", "-")
    results = {}

    # Рендер 1: ближняя сторона → дальняя (0° или 90° для горизонтальных)
    path_a = os.path.join(output_dir, f"{safe_name}_side_a.png")
    render_angle(reference_path, path_a, angle=None, room_name=room_name, room_analysis=room_analysis)
    results["side_a"] = path_a

    # Рендер 2: дальняя сторона → ближняя (+180°)
    img = Image.open(reference_path)
    w, h = img.size
    base_angle = 90 if w > h else 0
    flip_angle = base_angle + 180

    path_b = os.path.join(output_dir, f"{safe_name}_side_b.png")
    render_angle(reference_path, path_b, angle=flip_angle, room_name=room_name, room_analysis=room_analysis)
    results["side_b"] = path_b

    log.info(f"[{room_name}] 2 ракурса: side_a ({base_angle}°), side_b ({flip_angle}°)")
    return results


def render_angle(reference_path: str, output_path: str, angle: int = None, room_name: str = "", room_analysis: str = "") -> str:
    """
    Генерирует фото комнаты на уровне глаз.
    Горизонтальные референсы поворачиваются на 90° → все становятся вертикальными.
    Рендер всегда по длинной стороне сверху вниз.
    Если angle задан вручную — используется он.

    Принимает:
        reference_path — путь к референсу (вид сверху)
        output_path — путь для сохранения PNG
        angle — угол поворота (None = авто, иначе ручной)
        room_name — имя комнаты
        room_analysis — анализ комнаты из Слоя 1

    Возвращает:
        путь к сохранённому изображению
    """
    if not os.path.exists(reference_path):
        raise FileNotFoundError(f"Референс не найден: {reference_path}")

    img = Image.open(reference_path)
    orig_w, orig_h = img.size

    # Авто: горизонтальный → поворот 90°, вертикальный → без поворота
    if angle is None:
        angle = 90 if orig_w > orig_h else 0

    log.info(f"[{room_name}] Рендер | {orig_w}x{orig_h} | угол {angle}°")

    # Апскейл до минимального размера
    long_side = max(orig_w, orig_h)
    if long_side < REF_MIN_SIZE:
        scale = REF_MIN_SIZE / long_side
        img = img.resize((int(orig_w * scale), int(orig_h * scale)), Image.LANCZOS)
        log.info(f"[{room_name}] Апскейл: {orig_w}x{orig_h} → {img.size[0]}x{img.size[1]}")

    # Поворот если нужен
    if angle != 0:
        img = img.rotate(angle, expand=True, fillcolor=(255, 255, 255))

    # Сохраняем подготовленное изображение как промежуточный артефакт
    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)
    safe_name = room_name.replace(" ", "_").replace("/", "-")
    prepared_path = os.path.join(output_dir, f"{safe_name}_prepared_{angle}deg.png")
    img.save(prepared_path)
    log.info(f"[{room_name}] Подготовленный референс: {prepared_path} ({img.size[0]}x{img.size[1]})")

    # Кодируем в base64
    buf = io.BytesIO()
    img_rgb = img.convert("RGB") if img.mode == "RGBA" else img
    img_rgb.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    # Собираем промпт с анализом комнаты
    prompt = LAYER3_ANGLE_PROMPT
    if room_analysis:
        prompt += f"\n\nRoom context:\n{room_analysis}"

    # Отправляем в OSMI
    t_start = time.monotonic()
    result_b64 = call_osmi_image(prompt, img_b64, f"{room_name}/angle{angle}")
    osmi_sec = round(time.monotonic() - t_start, 2)

    # Сохраняем результат
    img_bytes = base64.b64decode(result_b64)
    with open(output_path, "wb") as f:
        f.write(img_bytes)

    # Сохраняем мету
    meta = {
        "layer": 3,
        "room": room_name,
        "angle": angle,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt": prompt,
        "timing": {"osmi_call_sec": osmi_sec},
        "output_kb": len(img_bytes) // 1024,
    }
    meta["original_size"] = [orig_w, orig_h]
    meta["auto_angle"] = angle
    meta_path = output_path.replace(".png", "_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    log.info(f"[{room_name}] Рендер {angle}° сохранён: {output_path} ({len(img_bytes) // 1024} KB)")
    return output_path
