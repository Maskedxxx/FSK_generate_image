"""
Слой 4: Общий рендер квартиры сверху.

Берёт все референсы комнат (уменьшенные до 700x700) + апскейленную схему,
отправляет в OSMI → получает единое изображение всей квартиры сверху.

Функции:
    render_composite()  — основная: все референсы + схема → общий рендер
"""

import base64
import io
import json
import os
import time
from datetime import datetime, timezone
from PIL import Image

from ..prompts import LAYER4_COMPOSITE_PROMPT
from ..osmi_client import call_osmi_image
from ..logger import get_logger

log = get_logger("fsk.layer4")

COMPOSITE_SIZE = 700  # размер для уменьшения референсов


def render_composite(
    schema_path: str,
    reference_paths: list[str],
    output_dir: str,
) -> str:
    """
    Генерирует общий рендер всей квартиры сверху.

    Принимает:
        schema_path — путь к апскейленной схеме
        reference_paths — список путей к референсам комнат
        output_dir — папка для сохранения

    Выполняет:
        1. Уменьшает каждый референс до 700x700
        2. Сохраняет уменьшенные как промежуточные артефакты
        3. Собирает коллаж: схема + все референсы
        4. Отправляет в OSMI
        5. Сохраняет результат

    Возвращает:
        путь к сохранённому изображению
    """
    os.makedirs(output_dir, exist_ok=True)

    if not os.path.exists(schema_path):
        raise FileNotFoundError(f"Схема не найдена: {schema_path}")

    log.info(f"Слой 4: общий рендер | {len(reference_paths)} комнат")

    # Уменьшаем схему и все референсы, собираем в вертикальный коллаж
    images = []

    # Схема
    schema = Image.open(schema_path)
    schema_thumb = _resize_to_fit(schema, COMPOSITE_SIZE)
    schema_thumb_path = os.path.join(output_dir, "schema_thumb.png")
    schema_thumb.save(schema_thumb_path)
    images.append(schema_thumb)
    log.info(f"Схема: {schema.size} → {schema_thumb.size}")

    # Референсы комнат
    for i, ref_path in enumerate(reference_paths):
        if not os.path.exists(ref_path):
            log.warning(f"Референс не найден: {ref_path}")
            continue
        ref = Image.open(ref_path)
        ref_thumb = _resize_to_fit(ref, COMPOSITE_SIZE)
        thumb_path = os.path.join(output_dir, f"ref_thumb_{i}.png")
        ref_thumb.save(thumb_path)
        images.append(ref_thumb)
        log.info(f"Референс {i}: {ref.size} → {ref_thumb.size}")

    # Собираем коллаж (горизонтальный ряд)
    total_w = sum(img.width for img in images) + (len(images) - 1) * 10
    max_h = max(img.height for img in images)
    collage = Image.new("RGB", (total_w, max_h), (255, 255, 255))
    x = 0
    for img in images:
        collage.paste(img, (x, (max_h - img.height) // 2))
        x += img.width + 10

    collage_path = os.path.join(output_dir, "collage.png")
    collage.save(collage_path)
    log.info(f"Коллаж: {collage.size} → {collage_path}")

    # Кодируем коллаж
    buf = io.BytesIO()
    collage.save(buf, format="PNG")
    collage_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    # Отправляем в OSMI
    t_start = time.monotonic()
    result_b64 = call_osmi_image(LAYER4_COMPOSITE_PROMPT, collage_b64, "layer4/composite")
    osmi_sec = round(time.monotonic() - t_start, 2)

    # Сохраняем результат
    img_bytes = base64.b64decode(result_b64)
    output_path = os.path.join(output_dir, "composite.png")
    with open(output_path, "wb") as f:
        f.write(img_bytes)

    # Сохраняем мету
    meta = {
        "layer": 4,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt": LAYER4_COMPOSITE_PROMPT,
        "references_count": len(reference_paths),
        "timing": {"osmi_call_sec": osmi_sec},
        "output_kb": len(img_bytes) // 1024,
    }
    meta_path = os.path.join(output_dir, "L4_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    log.info(f"Общий рендер сохранён: {output_path} ({len(img_bytes) // 1024} KB)")
    return output_path


def _resize_to_fit(img: Image.Image, max_size: int) -> Image.Image:
    """Уменьшает изображение чтобы вписать в max_size x max_size."""
    w, h = img.size
    if max(w, h) <= max_size:
        return img
    scale = max_size / max(w, h)
    new_w = int(w * scale)
    new_h = int(h * scale)
    return img.resize((new_w, new_h), Image.LANCZOS)
