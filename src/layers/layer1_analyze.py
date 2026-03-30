"""
Слой 1: Анализ планировки квартиры.

Принимает изображение планировки → отправляет в Gemini 3 Flash →
получает JSON с помещениями → валидирует → вырезает crop'ы.

Функции:
    analyze_floorplan()     — основная: изображение → dict с rooms + crop'ы
    _encode_image()         — читает файл → base64
    _call_api()             — вызов Gemini через OpenRouter (с retry до 3 раз)
    _parse_response()       — текст → JSON (убирает markdown-обёртку)
    _validate_response()    — JSON → pydantic-модель FloorplanResult
    _crop_rooms()           — вырезает комнаты по box_2d координатам
"""

import requests
import base64
import json
import os
import time
from PIL import Image

from ..config import OPENROUTER_API_KEY, LAYER1_MODEL
from ..prompts import LAYER1_SYSTEM_PROMPT, LAYER1_ANALYSIS_PROMPT
from ..models import FloorplanResult
from ..logger import get_logger

log = get_logger("fsk.layer1")

# Настройки retry
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # экспоненциальный backoff (секунды)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MIN_CROP_SIZE_PX = 10  # минимальный размер crop'а в пикселях


def analyze_floorplan(image_path: str, output_dir: str = None) -> dict:
    """
    Анализирует планировку квартиры через Gemini 3 Flash.
    Если указан output_dir — вырезает каждую комнату по bbox и сохраняет.

    Принимает:
        image_path — путь к изображению планировки (JPG, PNG)
        output_dir — папка для сохранения crop'ов (опционально)

    Выполняет:
        1. Кодирует изображение в base64
        2. Отправляет в Gemini (с retry до 3 раз)
        3. Парсит JSON из ответа
        4. Валидирует через pydantic
        5. Вырезает crop'ы (если output_dir)

    Возвращает:
        dict {analysis, rooms: [{name, area, shape, box_2d, crop_path?}]}

    Ошибки:
        ValueError — невалидный ответ модели или пустой rooms
        requests.HTTPError — API недоступен после 3 попыток
        FileNotFoundError — файл изображения не найден
    """
    # Проверяем что файл существует
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Файл планировки не найден: {image_path}")

    log.info(f"Анализ планировки: {image_path}")

    # Кодируем изображение
    img_base64 = _encode_image(image_path)
    log.info(f"Изображение закодировано: {len(img_base64) // 1024} KB base64")

    # Отправляем в API (с retry)
    raw_response = _call_api(img_base64)
    log.info(f"Ответ от модели: {len(raw_response)} символов")

    # Парсим JSON
    parsed = _parse_response(raw_response)
    log.info(f"JSON распарсен: {len(parsed.get('rooms', []))} помещений")

    # Валидируем через pydantic
    validated = _validate_response(parsed)
    log.info(f"Валидация пройдена: {len(validated.rooms)} помещений")

    # Конвертируем обратно в dict
    result = validated.model_dump()

    # Вырезаем crop'ы если указана папка
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        result = _crop_rooms(image_path, result, output_dir)

    return result


# === ВНУТРЕННИЕ ФУНКЦИИ ===


def _encode_image(image_path: str) -> str:
    """
    Читает изображение и кодирует в base64.

    Принимает:
        image_path — путь к файлу

    Возвращает:
        base64-строка
    """
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _call_api(img_base64: str) -> str:
    """
    Вызов Gemini 3 Flash через OpenRouter с retry.

    Принимает:
        img_base64 — изображение в base64

    Retry логика:
        - До 3 попыток
        - Задержка: 1, 2, 4 сек (exponential backoff)
        - Retry на: 429, 5xx, timeout
        - Без retry на: 401 (ключ невалидный)

    Возвращает:
        текст ответа модели

    Ошибки:
        requests.HTTPError — после исчерпания попыток
    """
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            log.info(f"Запрос к Gemini (попытка {attempt}/{MAX_RETRIES})")

            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": LAYER1_MODEL,
                    "messages": [
                        {"role": "system", "content": LAYER1_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": LAYER1_ANALYSIS_PROMPT},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"},
                                },
                            ],
                        },
                    ],
                    "temperature": 0,
                },
                timeout=60,
            )

            # 401 — ключ невалидный, без retry
            if response.status_code == 401:
                log.error(f"API ключ невалидный (401): {response.text[:300]}")
                response.raise_for_status()

            # Retryable ошибки
            if response.status_code in RETRYABLE_STATUS_CODES:
                log.warning(f"API вернул {response.status_code}, retry через {RETRY_DELAYS[attempt - 1]} сек")
                last_error = requests.HTTPError(f"HTTP {response.status_code}", response=response)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAYS[attempt - 1])
                continue

            # Проверяем остальные ошибки
            response.raise_for_status()

            # Парсим ответ
            data = response.json()
            if "choices" not in data:
                log.error(f"Ответ без choices: {json.dumps(data, ensure_ascii=False)[:500]}")
                raise ValueError(f"API вернул ответ без choices: {json.dumps(data, ensure_ascii=False)[:300]}")

            return data["choices"][0]["message"]["content"]

        except requests.Timeout:
            log.warning(f"Timeout (попытка {attempt}/{MAX_RETRIES})")
            last_error = requests.Timeout("API timeout")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAYS[attempt - 1])

        except requests.ConnectionError as e:
            log.warning(f"Connection error (попытка {attempt}/{MAX_RETRIES}): {e}")
            last_error = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAYS[attempt - 1])

    # Все попытки исчерпаны
    log.error(f"Все {MAX_RETRIES} попыток исчерпаны. Последняя ошибка: {last_error}")
    raise last_error


def _parse_response(text: str) -> dict:
    """
    Парсит JSON из ответа модели.
    Убирает markdown-обёртку если есть.

    Принимает:
        text — сырой текст ответа модели

    Возвращает:
        dict с данными

    Ошибки:
        ValueError — если не удалось распарсить JSON
    """
    if not text or not text.strip():
        raise ValueError("Модель вернула пустой ответ")

    clean = text.strip()

    # Убираем ```json ... ```
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1]
        clean = clean.rsplit("```", 1)[0]

    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        log.error(f"Ошибка парсинга JSON: {e}\nОтвет модели: {text[:500]}")
        raise ValueError(f"Не удалось распарсить JSON из ответа модели: {e}\nОтвет: {text[:500]}")


def _validate_response(data: dict) -> FloorplanResult:
    """
    Валидирует ответ через pydantic-модель.

    Принимает:
        data — dict из _parse_response()

    Возвращает:
        FloorplanResult

    Ошибки:
        ValueError — если данные не соответствуют схеме
    """
    try:
        result = FloorplanResult(**data)
        return result
    except Exception as e:
        log.error(f"Ошибка валидации: {e}\nДанные: {json.dumps(data, ensure_ascii=False)[:500]}")
        raise ValueError(f"Ответ модели не соответствует схеме: {e}")


def _crop_rooms(image_path: str, analysis: dict, output_dir: str) -> dict:
    """
    Вырезает каждую комнату по полигону с полупрозрачным оверлеем за границами.
    Усиливает контраст стен. Расширяет полигон на 7px для захвата стен.

    Принимает:
        image_path — путь к исходному изображению
        analysis — dict с rooms[].polygon
        output_dir — папка для сохранения crop'ов

    Возвращает:
        analysis с добавленными crop_path для каждой комнаты
    """
    from PIL import ImageDraw, ImageEnhance

    img = Image.open(image_path)
    img_w, img_h = img.size
    os.makedirs(output_dir, exist_ok=True)
    log.info(f"Исходное изображение: {img_w}x{img_h} px")

    # Усиливаем контраст стен
    img_enhanced = ImageEnhance.Contrast(img).enhance(2.0)

    # Рисуем общую визуализацию полигонов на схеме
    _save_polygons_overlay(img, analysis, output_dir, img_w, img_h)

    skipped = []

    for i, room in enumerate(analysis["rooms"]):
        polygon = room.get("polygon")
        room_label = room["name"] if room["name"] != "Nan" else f"room_{room['area']}m2"

        # Нет полигона или мало точек
        if not polygon or len(polygon) < 3:
            log.warning(f"[{room_label}] Нет полигона или мало точек — пропускаем")
            skipped.append({"name": room_label, "reason": "нет полигона"})
            continue

        # Конвертируем нормализованные координаты в пиксели
        px_points = []
        for x, y in polygon:
            px_x = int(x / 1000 * img_w)
            px_y = int(y / 1000 * img_h)
            px_points.append((px_x, px_y))

        # Проверяем минимальный размер
        xs = [p[0] for p in px_points]
        ys = [p[1] for p in px_points]
        poly_w = max(xs) - min(xs)
        poly_h = max(ys) - min(ys)
        if poly_w < MIN_CROP_SIZE_PX or poly_h < MIN_CROP_SIZE_PX:
            log.warning(f"[{room_label}] Полигон слишком маленький: {poly_w}x{poly_h} px — пропускаем")
            skipped.append({"name": room_label, "reason": f"полигон {poly_w}x{poly_h} px"})
            continue

        # Расширяем полигон на 7px чтобы стены гарантированно внутри
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

        # Bbox с 10% padding для контекста соседей
        pad_x = int(poly_w * 0.10)
        pad_y = int(poly_h * 0.10)
        bbox = (
            max(0, min(xs) - pad_x),
            max(0, min(ys) - pad_y),
            min(img_w, max(xs) + pad_x),
            min(img_h, max(ys) + pad_y),
        )

        # Вырезаем область с контекстом (усиленный контраст)
        room_crop = img_enhanced.crop(bbox)

        # Полупрозрачный белый оверлей за полигоном (70%)
        overlay = Image.new("RGBA", room_crop.size, (255, 255, 255, 180))
        mask = Image.new("L", (img_w, img_h), 255)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.polygon(expanded_points, fill=0)  # внутри расширенного полигона — без оверлея
        mask_crop = mask.crop(bbox)

        # Накладываем оверлей
        room_crop = room_crop.convert("RGBA")
        room_crop.paste(overlay, mask=mask_crop)
        room_crop = room_crop.convert("RGB")

        # Сохраняем
        safe_name = room_label.replace(" ", "_").replace("/", "-")
        crop_path = os.path.join(output_dir, f"{i + 1}_{safe_name}_crop.png")
        room_crop.save(crop_path)

        room["crop_path"] = crop_path
        log.info(f"[{room_label}] Crop: {room_crop.size[0]}x{room_crop.size[1]} px → {crop_path}")

    # Добавляем инфо о пропущенных
    if skipped:
        analysis["skipped_rooms"] = skipped
        log.warning(f"Пропущено помещений: {len(skipped)}")

    return analysis


def _save_polygons_overlay(img: Image.Image, analysis: dict, output_dir: str, img_w: int, img_h: int) -> None:
    """
    Рисует все полигоны на копии схемы и сохраняет как schema_with_polygons.png.
    Для визуальной отладки — видно как модель разметила комнаты.

    Принимает:
        img — исходное изображение
        analysis — dict с rooms[].polygon
        output_dir — папка для сохранения
        img_w, img_h — размеры изображения
    """
    from PIL import ImageDraw

    colors = ["red", "blue", "green", "orange", "purple", "cyan", "magenta", "yellow"]
    overlay = img.copy()
    draw = ImageDraw.Draw(overlay)

    for i, room in enumerate(analysis.get("rooms", [])):
        polygon = room.get("polygon")
        if not polygon or len(polygon) < 3:
            continue

        room_label = room["name"] if room["name"] != "Nan" else f"room_{room['area']}m2"
        color = colors[i % len(colors)]

        # Конвертируем в пиксели
        px_points = [(int(x / 1000 * img_w), int(y / 1000 * img_h)) for x, y in polygon]

        # Рисуем полигон
        draw.polygon(px_points, outline=color, width=3)

        # Подписываем по центру
        cx = sum(p[0] for p in px_points) // len(px_points)
        cy = sum(p[1] for p in px_points) // len(px_points)
        draw.text((cx - 20, cy - 10), f"{room_label}\n{room.get('area', '?')}m²", fill=color)

    overlay_path = os.path.join(output_dir, "schema_with_polygons.png")
    overlay.save(overlay_path)
    log.info(f"Визуализация полигонов: {overlay_path}")
