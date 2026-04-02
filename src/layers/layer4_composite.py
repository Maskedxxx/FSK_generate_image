"""
Слой 4: Общий рендер квартиры сверху.

Двухэтапный подход:
    1. Stitch — склейка референсов на холст по полигонам (код, без AI)
    2. Refine — доработка проходов/стен через OSMI dual-ноду (AI)

Функции:
    render_composite()      — основная: stitch → refine → результат
    stitch_references()     — склейка референсов по координатам
    refine_composite()      — AI-доработка по схеме
"""

import base64
import io
import json
import os
import time
from datetime import datetime, timezone
from PIL import Image, ImageDraw

from ..prompts import LAYER4_REFINE_PROMPT
from ..osmi_client import call_osmi_image_dual
from ..logger import get_logger

log = get_logger("fsk.layer4")

COMPOSITE_SIZE = 700  # не используется, стичим в натуральный размер


def render_composite(
    schema_path: str,
    reference_paths: list[str],
    output_dir: str,
    rooms: list[dict] = None,
) -> str:
    """
    Генерирует общий рендер квартиры: stitch → refine.

    Принимает:
        schema_path — путь к апскейленной схеме
        reference_paths — пути к референсам комнат (в порядке rooms)
        output_dir — папка для сохранения
        rooms — список комнат из analysis (с polygon, name, area)

    Возвращает:
        путь к финальному изображению
    """
    os.makedirs(output_dir, exist_ok=True)

    if not os.path.exists(schema_path):
        raise FileNotFoundError(f"Схема не найдена: {schema_path}")

    if rooms is None:
        raise ValueError("rooms обязателен — нужны полигоны для склейки")

    log.info(f"Слой 4: {len(reference_paths)} комнат")

    # === Шаг 1: Stitch ===
    stitched = stitch_references(schema_path, reference_paths, rooms)
    stitched_path = os.path.join(output_dir, "stitched.png")
    stitched.save(stitched_path)
    log.info(f"Stitch: {stitched.size} → {stitched_path}")

    # === Шаг 2: Refine ===
    t_start = time.monotonic()
    refined = refine_composite(stitched, schema_path)
    osmi_sec = round(time.monotonic() - t_start, 2)

    output_path = os.path.join(output_dir, "composite.png")
    refined.save(output_path)
    log.info(f"Refine: {refined.size} → {output_path} ({osmi_sec} сек)")

    # Мета
    meta = {
        "layer": 4,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt": LAYER4_REFINE_PROMPT,
        "references_count": len(reference_paths),
        "rooms": [r.get("name", "?") for r in rooms],
        "timing": {"osmi_call_sec": osmi_sec},
    }
    with open(os.path.join(output_dir, "L4_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    return output_path


def stitch_references(
    schema_path: str,
    reference_paths: list[str],
    rooms: list[dict],
) -> Image.Image:
    """
    Склеивает референсы на холст по координатам полигонов.

    Принимает:
        schema_path — путь к схеме (определяет размер холста)
        reference_paths — пути к референсам (в порядке rooms)
        rooms — комнаты с polygon

    Возвращает:
        PIL Image — склеенная квартира
    """
    schema = Image.open(schema_path)
    w, h = schema.size

    canvas = Image.new("RGB", (w, h), (255, 255, 255))

    for ref_path, room in zip(reference_paths, rooms):
        polygon = room.get("polygon", [])
        name = room.get("name", "?")

        if len(polygon) < 3:
            log.warning(f"[{name}] Нет полигона — пропускаем")
            continue

        if not os.path.exists(ref_path):
            log.warning(f"[{name}] Референс не найден: {ref_path}")
            continue

        # Координаты в пиксели
        px_points = [(int(x / 1000 * w), int(y / 1000 * h)) for x, y in polygon]
        xs = [p[0] for p in px_points]
        ys = [p[1] for p in px_points]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        poly_w = x_max - x_min
        poly_h = y_max - y_min

        if poly_w < 5 or poly_h < 5:
            continue

        # Ресайз референса до размера полигона
        ref = Image.open(ref_path)
        ref_resized = ref.resize((poly_w, poly_h), Image.LANCZOS)

        # Маска по полигону
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).polygon(px_points, fill=255)
        mask_crop = mask.crop((x_min, y_min, x_max, y_max))

        canvas.paste(ref_resized, (x_min, y_min), mask_crop)
        log.info(f"[{name}] {ref.size} → {poly_w}x{poly_h} @ ({x_min},{y_min})")

    # Белые стены поверх
    draw = ImageDraw.Draw(canvas)
    for room in rooms:
        polygon = room.get("polygon", [])
        if len(polygon) < 3:
            continue
        px_points = [(int(x / 1000 * w), int(y / 1000 * h)) for x, y in polygon]
        draw.polygon(px_points, outline=(255, 255, 255), width=4)

    return canvas


def refine_composite(stitched: Image.Image, schema_path: str) -> Image.Image:
    """
    AI-доработка склейки: проходы, стены, стыки по схеме.

    Принимает:
        stitched — склеенная квартира (PIL Image)
        schema_path — путь к апскейленной схеме

    Возвращает:
        PIL Image — доработанная квартира
    """
    schema = Image.open(schema_path)

    stitched_b64 = _img_to_b64(stitched)
    schema_b64 = _img_to_b64(schema)

    result_b64 = call_osmi_image_dual(
        LAYER4_REFINE_PROMPT, stitched_b64, schema_b64, "layer4/refine"
    )

    img_bytes = base64.b64decode(result_b64)
    return Image.open(io.BytesIO(img_bytes))


def _img_to_b64(img: Image.Image) -> str:
    """PIL Image → base64 PNG."""
    buf = io.BytesIO()
    img_rgb = img.convert("RGB") if img.mode != "RGB" else img
    img_rgb.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")
