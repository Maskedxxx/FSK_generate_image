"""
Сборка референсов обратно на схему по координатам полигонов.

Берёт координаты из analysis.json, ресайзит каждый референс
до размера полигона, вставляет точно по координатам.
Геометрия 100% совпадает со схемой.

Использование:
    python scripts/stitch_references.py

Результат: scripts/debug_stitch/stitched.png
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw

ANALYSIS = "results/2026-04-01_5b1bdd01/L1_crops/analysis.json"
SCHEMA = "results/2026-04-01_5b1bdd01/L1_crops/schema_x2.png"
REFS_DIR = "scripts/debug_references"
OUTPUT_DIR = "scripts/debug_stitch"


def stitch_references(schema_path, analysis_path, refs_dir, output_dir):
    """Вклеивает референсы на пустой холст по координатам полигонов."""
    os.makedirs(output_dir, exist_ok=True)

    # Размер схемы = размер холста
    schema = Image.open(schema_path)
    w, h = schema.size
    print(f"Схема: {w}x{h}")

    with open(analysis_path, "r", encoding="utf-8") as f:
        analysis = json.load(f)

    # Холст — белый фон
    canvas = Image.new("RGB", (w, h), (255, 255, 255))

    for i, room in enumerate(analysis["rooms"]):
        name = room["name"] if room["name"] != "Nan" else f"room_{room['area']}m2"
        safe_name = name.replace(" ", "_").replace("/", "-")
        polygon = room.get("polygon", [])

        if len(polygon) < 3:
            print(f"  [{name}] Нет полигона — пропускаем")
            continue

        # Координаты полигона в пиксели
        px_points = [(int(x / 1000 * w), int(y / 1000 * h)) for x, y in polygon]

        # Bbox полигона
        xs = [p[0] for p in px_points]
        ys = [p[1] for p in px_points]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        poly_w = x_max - x_min
        poly_h = y_max - y_min

        # Ищем референс
        ref_path = os.path.join(refs_dir, f"{safe_name}.png")
        if not os.path.exists(ref_path):
            print(f"  [{name}] Референс не найден — пропускаем")
            continue

        # Ресайзим референс до размера полигона
        ref = Image.open(ref_path)
        ref_resized = ref.resize((poly_w, poly_h), Image.LANCZOS)

        # Создаём маску по полигону (для не-прямоугольных)
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).polygon(px_points, fill=255)
        mask_crop = mask.crop((x_min, y_min, x_max, y_max))

        # Вставляем с маской
        canvas.paste(ref_resized, (x_min, y_min), mask_crop)

        print(f"  [{name}] {ref.size} → {poly_w}x{poly_h} @ ({x_min},{y_min})")

    # Рисуем стены поверх (линии полигонов)
    draw = ImageDraw.Draw(canvas)
    for room in analysis["rooms"]:
        polygon = room.get("polygon", [])
        if len(polygon) < 3:
            continue
        px_points = [(int(x / 1000 * w), int(y / 1000 * h)) for x, y in polygon]
        draw.polygon(px_points, outline=(255, 255, 255), width=4)

    # Сохраняем
    output_path = os.path.join(output_dir, "stitched.png")
    canvas.save(output_path)
    print(f"\nРезультат: {output_path} ({canvas.size})")

    # Сохраняем версию со схемой поверх (для сравнения)
    overlay = canvas.copy()
    schema_alpha = schema.convert("RGBA")
    # Делаем схему полупрозрачной
    alpha = Image.new("L", schema.size, 80)
    schema_alpha.putalpha(alpha)
    overlay = overlay.convert("RGBA")
    overlay = Image.alpha_composite(overlay, schema_alpha)
    overlay_path = os.path.join(output_dir, "stitched_with_schema.png")
    overlay.convert("RGB").save(overlay_path)
    print(f"С наложением схемы: {overlay_path}")

    return output_path


if __name__ == "__main__":
    stitch_references(SCHEMA, ANALYSIS, REFS_DIR, OUTPUT_DIR)
