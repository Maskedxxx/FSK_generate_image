"""
Отправляет склеенный референс + апскейл схему в dual-ноду.
Модель доработает: проходы, стены, соответствие схеме.

Использование:
    python scripts/refine_stitched.py

Вход: scripts/debug_stitch/stitched.png + results/.../schema_x2.png
Результат: scripts/debug_stitch/refined.png
"""

import sys
import os
import base64
import io
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
from src.osmi_client import call_osmi_image_dual

STITCHED = "scripts/debug_stitch/stitched.png"
SCHEMA = "results/2026-04-01_5b1bdd01/L1_crops/schema_x2.png"
OUTPUT_DIR = "scripts/debug_stitch"

REFINE_PROMPT = """Ты получаешь ДВА изображения:

ИЗОБРАЖЕНИЕ 1 — СКЛЕЕННЫЙ РЕФЕРЕНС квартиры сверху. Интерьеры комнат уже на месте, геометрия правильная. НО проходы между комнатами НЕ СООТВЕТСТВУЮТ схеме — это главная проблема которую ты ДОЛЖЕН исправить.

ИЗОБРАЖЕНИЕ 2 — ОРИГИНАЛЬНАЯ СХЕМА ПЛАНИРОВКИ. Это ЧЕРТЁЖ-ИСТИНА. На нём ТОЧНО показаны:
- ДВЕРНЫЕ ПРОЁМЫ — дуги/арки в стенах. Каждая дуга = реальный проход между комнатами
- СТЕНЫ — толстые чёрные линии. Где стена — там НЕЛЬЗЯ быть проходу
- ОКНА — двойные линии на внешних стенах

ТВОЯ ГЛАВНАЯ ЗАДАЧА — исправить ПРОХОДЫ МЕЖДУ КОМНАТАМИ:

Step by step:
1. Внимательно изучи СХЕМУ (изображение 2) — найди КАЖДЫЙ дверной проём (дуга в стене). Запомни ГДЕ ИМЕННО на стене находится каждый проход и КАКИЕ КОМНАТЫ он соединяет.
2. Теперь посмотри на РЕФЕРЕНС (изображение 1) — сравни: где на референсе есть проход, а на схеме стена? Где на схеме проход, а на референсе глухая стена? Каждое несоответствие — ОШИБКА.
3. ИСПРАВЬ каждую ошибку:
   - Где на схеме ДВЕРНОЙ ПРОЁМ → на референсе ДОЛЖЕН быть открытый проход (видно пол соседней комнаты)
   - Где на схеме СПЛОШНАЯ СТЕНА → на референсе ДОЛЖНА быть стена (без прохода)
4. Стены между комнатами — чёткие, белые, аккуратные, ТОЧНО как на схеме
5. Стыки между комнатами сгладь — переходы пола должны быть естественными
6. НЕ МЕНЯЙ интерьер внутри комнат — мебель, цвета, материалы оставь
7. НЕ МЕНЯЙ размеры и расположение комнат — геометрия уже правильная
8. Вид строго сверху, высокое разрешение, фотореализм
9. Без текста, надписей, водяных знаков

КРИТЕРИЙ УСПЕХА: если наложить схему на результат — все проходы и стены СОВПАДАЮТ."""


def img_to_b64(path):
    img = Image.open(path)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def main():
    print(f"Склеенный: {STITCHED}")
    print(f"Схема: {SCHEMA}")

    stitched_b64 = img_to_b64(STITCHED)
    schema_b64 = img_to_b64(SCHEMA)

    print(f"Отправляем в OSMI dual-ноду...")
    t = time.time()
    result_b64 = call_osmi_image_dual(REFINE_PROMPT, stitched_b64, schema_b64, "layer4/refine")
    elapsed = time.time() - t

    img_bytes = base64.b64decode(result_b64)
    output_path = os.path.join(OUTPUT_DIR, "refined.png")
    with open(output_path, "wb") as f:
        f.write(img_bytes)

    # Мета
    meta = {
        "prompt": REFINE_PROMPT,
        "timing_sec": round(elapsed, 2),
        "output_kb": len(img_bytes) // 1024,
    }
    with open(os.path.join(OUTPUT_DIR, "refine_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    print(f"Готово: {output_path} ({len(img_bytes) // 1024} KB, {elapsed:.1f} сек)")


if __name__ == "__main__":
    main()
