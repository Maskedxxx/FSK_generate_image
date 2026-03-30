"""
Эксперимент: полигонные координаты комнат от Gemini.

Отправляем схему → просим вернуть polygon точки для каждой комнаты →
рисуем полигоны на схеме → вырезаем каждую комнату по маске.

Запуск: python tests/experiments/test_polygon.py [путь к схеме]
"""

import sys
import os
import json
import base64
import requests
from PIL import Image, ImageDraw
from datetime import datetime

# Пути
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from src.config import OPENROUTER_API_KEY, LAYER1_MODEL

# Схема по умолчанию
DEFAULT_IMAGE = "/Users/mask/Downloads/конеткст_для_агента/Валидные/Снимок экрана 2026-03-10 130257.jpg"

# Папка результатов
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results", "experiments")

SYSTEM_PROMPT = """You are an expert architect and interior visualization specialist. You work with apartment floor plans daily — you instantly recognize every room type, understand wall structures, doorways, and how rooms connect to each other.

When you see a floor plan, you read it like a book: walls are thick dark lines, doorways are arc gaps, windows are parallel lines on external walls, and each area number marks one distinct room.

For each room, return POLYGON coordinates — a list of [x, y] points that precisely trace the INNER wall boundaries of that room.

Rules:
- Coordinates normalized 0-1000 (0 = left/top, 1000 = right/bottom of image)
- Every room has an ENTRANCE — a gap/break in its walls. Use this entrance as your ANCHOR: start tracing the polygon from the LEFT side of the entrance gap, then go CLOCKWISE along the inner walls back to the RIGHT side of the entrance.
- Trace walls PRECISELY — follow every corner, niche, angle
- For L-shaped or irregular rooms: use MORE points to trace the exact shape (6-10+ points)
- For rectangular rooms: 4-5 points (corners + entrance)
- Each area number on the plan = one separate room. Do NOT merge rooms.
- The info block with total area (like "C 14.05 / 20.40 / 22.68") is NOT a room — it's apartment metadata, skip it
- Identify rooms and do NOT cut the polygon too early — if you see these artifacts, the room CONTINUES:
  * Kitchen: stove, sink, fridge, countertop — if visible, room extends to include them
  * Bathroom: toilet, bathtub, shower — if visible, room extends to include them
  * Bedroom: bed, nightstand — if visible, room extends to include them
  * Hallway/closet: coat hangers, shoe rack, shelves — if visible, room extends to include them
  * Balcony/loggia: narrow external space
  * If room has NO recognizable artifacts — follow wall contour from entrance back to entrance

Return JSON without markdown wrapping."""

USER_PROMPT = """Analyze this floor plan carefully.

Step 1: Count ALL unique area numbers on the plan. Each one = one room.
Step 2: For each room, identify its function from furniture symbols.
Step 3: Trace the INNER walls precisely with polygon points.

JSON format:
{
  "rooms": [
    {
      "name": "room function (kitchen, bedroom, bathroom, hallway, balcony) or Nan",
      "area": area number from plan,
      "analysis": "reasoning step by step: 1) Where is the ENTRANCE (door gap) to this room? 2) What ARTIFACTS (furniture/appliances) are inside and do they belong to THIS room type? If artifact doesn't match room function — it's NOT in this room. 3) Describe each wall side: TOP wall — what is there, LEFT wall — what is there, BOTTOM wall — what is there, RIGHT wall — what is there. 4) Only then trace the polygon.",
      "walls": {
        "top": "what is along the top wall of this room",
        "left": "what is along the left wall",
        "bottom": "what is along the bottom wall",
        "right": "what is along the right wall"
      },
      "polygon_start": "describe where you start tracing: which corner or entrance side",
      "polygon_end": "describe where you end: should connect back to start",
      "polygon": [[x1,y1], [x2,y2], [x3,y3], ...]
    }
  ]
}

IMPORTANT:
- THINK before drawing: analyze wall shape first, then trace
- L-shaped rooms need 6+ points to trace the L
- Follow wall corners exactly
- Do NOT include apartment info blocks as rooms"""


def main():
    image_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_IMAGE

    if not os.path.exists(image_path):
        print(f"Файл не найден: {image_path}")
        return

    # Папка результатов
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(RESULTS_DIR, f"polygon_{timestamp}")
    os.makedirs(output_dir, exist_ok=True)

    print(f"Схема: {image_path}")
    print(f"Результаты: {output_dir}")

    # Кодируем изображение
    with open(image_path, "rb") as f:
        img_base64 = base64.b64encode(f.read()).decode("utf-8")

    # Запрос к Gemini
    print("\nЗапрос к Gemini...")
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": LAYER1_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": USER_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}},
                    ],
                },
            ],
            "temperature": 0,
        },
        timeout=60,
    )
    response.raise_for_status()

    # Парсим ответ
    text = response.json()["choices"][0]["message"]["content"]
    print(f"Ответ: {len(text)} символов")

    # Сохраняем сырой ответ
    with open(os.path.join(output_dir, "raw_response.txt"), "w", encoding="utf-8") as f:
        f.write(text)

    # Парсим JSON
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1].rsplit("```", 1)[0]

    try:
        data = json.loads(clean)
    except json.JSONDecodeError as e:
        print(f"Ошибка парсинга JSON: {e}")
        print(f"Ответ: {text[:500]}")
        return

    # Сохраняем JSON
    with open(os.path.join(output_dir, "polygons.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    rooms = data.get("rooms", [])
    print(f"\nНайдено комнат: {len(rooms)}")

    # Загружаем изображение
    img = Image.open(image_path)
    img_w, img_h = img.size
    print(f"Размер изображения: {img_w}x{img_h}")

    # Цвета для разных комнат
    colors = ["red", "blue", "green", "orange", "purple", "cyan"]

    # === Рисуем все полигоны на схеме ===
    img_with_polygons = img.copy()
    draw = ImageDraw.Draw(img_with_polygons)

    for i, room in enumerate(rooms):
        polygon = room.get("polygon", [])
        area = room.get("area", "?")
        name = room.get("name", "Nan")
        color = colors[i % len(colors)]

        print(f"\n  [{i}] {name} ({area} м²) — {len(polygon)} точек")

        if len(polygon) < 3:
            print(f"      Мало точек — пропускаем")
            continue

        # Конвертируем нормализованные координаты в пиксели
        px_points = []
        for x, y in polygon:
            px_x = int(x / 1000 * img_w)
            px_y = int(y / 1000 * img_h)
            px_points.append((px_x, px_y))

        # Рисуем полигон на общей схеме
        draw.polygon(px_points, outline=color, width=3)

        # Подписываем
        cx = sum(p[0] for p in px_points) // len(px_points)
        cy = sum(p[1] for p in px_points) // len(px_points)
        draw.text((cx - 20, cy - 10), f"{name}\n{area}m²", fill=color)

        # === Усиливаем контраст стен ===
        from PIL import ImageEnhance
        img_enhanced = ImageEnhance.Contrast(img).enhance(2.0)  # стены чернее

        # === Вырезаем комнату: полигон чёткий, за полигоном полупрозрачный ===
        # Берём bbox с padding 10% для контекста соседей
        xs = [p[0] for p in px_points]
        ys = [p[1] for p in px_points]
        poly_w = max(xs) - min(xs)
        poly_h = max(ys) - min(ys)
        pad_x = int(poly_w * 0.10)
        pad_y = int(poly_h * 0.10)
        bbox = (
            max(0, min(xs) - pad_x),
            max(0, min(ys) - pad_y),
            min(img_w, max(xs) + pad_x),
            min(img_h, max(ys) + pad_y),
        )

        # Вырезаем область с контекстом
        room_crop = img_enhanced.crop(bbox)

        # Расширяем полигон на 3px чтобы стены гарантированно внутри
        cx = sum(p[0] for p in px_points) / len(px_points)
        cy = sum(p[1] for p in px_points) / len(px_points)
        expanded_points = []
        for px, py in px_points:
            dx = px - cx
            dy = py - cy
            dist = (dx**2 + dy**2) ** 0.5
            if dist > 0:
                expanded_points.append((int(px + dx / dist * 7), int(py + dy / dist * 7)))
            else:
                expanded_points.append((px, py))

        # Создаём полупрозрачный белый оверлей за полигоном
        overlay = Image.new("RGBA", room_crop.size, (255, 255, 255, 180))  # белый 70% непрозрачности
        mask = Image.new("L", (img_w, img_h), 255)  # всё белое (оверлей везде)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.polygon(expanded_points, fill=0)  # внутри расширенного полигона — без оверлея
        mask_crop = mask.crop(bbox)

        # Накладываем: оригинал + оверлей за полигоном
        room_crop = room_crop.convert("RGBA")
        room_crop.paste(overlay, mask=mask_crop)
        room_crop = room_crop.convert("RGB")

        # Сохраняем crop
        safe_name = (name if name != "Nan" else f"room_{area}m2").replace(" ", "_").replace("/", "-")
        crop_path = os.path.join(output_dir, f"{i + 1}_{safe_name}_crop.png")
        room_crop.save(crop_path)
        print(f"      Crop: {room_crop.size[0]}x{room_crop.size[1]} → {crop_path}")

    # Сохраняем схему с полигонами
    overlay_path = os.path.join(output_dir, "schema_with_polygons.png")
    img_with_polygons.save(overlay_path)
    print(f"\nСхема с полигонами: {overlay_path}")
    print(f"Результаты: {output_dir}")


if __name__ == "__main__":
    main()
