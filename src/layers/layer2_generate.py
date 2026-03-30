"""
Слой 2: Генерация референса (вид сверху).

Принимает crop помещения + метаданные + опросник →
отправляет в Gemini 3.1 Flash Image → получает фотореалистичный вид сверху.

Функции:
    generate_room()         — основная: crop + опросник → PNG референс
    _upscale_and_encode()   — масштабирование crop'а до 1024px + base64
    _call_api()             — вызов Gemini через OpenRouter (с retry до 3 раз)
    _extract_image()        — извлечение base64 изображения из ответа модели
"""

import requests
import base64
import io
import os
import json
import time
from PIL import Image

from ..config import OPENROUTER_API_KEY, GEMINI_MODEL
from ..prompts import build_layer2_prompt, LAYER2_PASS1_SYSTEM, LAYER2_PASS1_USER, LAYER2_PASS2_SYSTEM
from ..logger import get_logger

log = get_logger("fsk.layer2")

# Настройки
MIN_LONG_SIDE = 1024  # минимальный размер длинной стороны для отправки
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def generate_room(room: dict, answers: dict, crop_path: str, output_path: str) -> str:
    """
    Генерирует фотореалистичный референс комнаты (вид сверху).

    Принимает:
        room — метаданные комнаты из Слоя 1 {name, area, shape, crop_path}
        answers — валидированные ответы опросника
        crop_path — путь к вырезанному изображению помещения
        output_path — путь для сохранения PNG

    Выполняет:
        1. Масштабирует crop до мин. 1024px
        2. Собирает промпт (системный + юзер с метаданными и опросником)
        3. Отправляет в Gemini (с retry до 3 раз)
        4. Извлекает изображение из ответа
        5. Сохраняет PNG

    Возвращает:
        путь к сохранённому изображению

    Ошибки:
        FileNotFoundError — crop файл не найден
        ValueError — модель не вернула изображение
        requests.HTTPError — API недоступен после 3 попыток
    """
    room_name = room.get("name", "unknown")

    # Проверяем что crop существует
    if not os.path.exists(crop_path):
        raise FileNotFoundError(f"Crop файл не найден: {crop_path}")

    log.info(f"[{room_name}] Генерация референса: {room.get('area', '?')} м², {room.get('shape', '?')}")

    # Масштабируем crop
    crop_base64 = _upscale_and_encode(crop_path, room_name)

    # Расчёт размеров для промпта
    import math
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
    pass1_response = _call_api(LAYER2_PASS1_SYSTEM, pass1_user, crop_base64, f"{room_name}/pass1")
    empty_room_b64 = _extract_image(pass1_response, f"{room_name}/pass1")

    # Сохраняем пустую комнату как промежуточный артефакт
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    empty_path = output_path.replace(".png", "_empty.png")
    with open(empty_path, "wb") as f:
        f.write(base64.b64decode(empty_room_b64))
    log.info(f"[{room_name}] Проход 1 готов: {empty_path}")

    # === ПРОХОД 2: Наполнение мебелью ===
    log.info(f"[{room_name}] Проход 2: наполнение мебелью...")
    _, pass2_user = build_layer2_prompt(room, answers)
    pass2_response = _call_api_two_images(
        system_prompt=LAYER2_PASS2_SYSTEM,
        user_prompt=pass2_user,
        image1_base64=empty_room_b64,
        image2_base64=crop_base64,
        room_name=f"{room_name}/pass2",
    )
    reference_b64 = _extract_image(pass2_response, f"{room_name}/pass2")

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


def _call_api(system_prompt: str, user_prompt: str, img_base64: str, room_name: str = "") -> dict:
    """
    Вызов Gemini 3.1 Flash Image через OpenRouter с retry.

    Принимает:
        system_prompt — системный промпт
        user_prompt — юзер-промпт с метаданными и опросником
        img_base64 — crop изображения в base64
        room_name — для логирования

    Retry логика:
        - До 3 попыток, задержка 1/2/4 сек
        - Retry на: 429, 5xx, timeout
        - Без retry на: 401

    Возвращает:
        dict — полный ответ API (data["choices"][0]["message"])

    Ошибки:
        requests.HTTPError — после исчерпания попыток
    """
    # Собираем messages
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": user_prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_base64}"}}
        ]
    })

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            log.info(f"[{room_name}] Запрос к Gemini (попытка {attempt}/{MAX_RETRIES})")

            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": GEMINI_MODEL,
                    "messages": messages,
                    "temperature": 0,
                },
                timeout=120,
            )

            # 401 — без retry
            if response.status_code == 401:
                log.error(f"[{room_name}] API ключ невалидный (401): {response.text[:300]}")
                response.raise_for_status()

            # Retryable
            if response.status_code in RETRYABLE_STATUS_CODES:
                log.warning(f"[{room_name}] API вернул {response.status_code}, retry через {RETRY_DELAYS[attempt - 1]} сек")
                last_error = requests.HTTPError(f"HTTP {response.status_code}", response=response)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAYS[attempt - 1])
                continue

            response.raise_for_status()

            data = response.json()
            if "choices" not in data:
                log.error(f"[{room_name}] Ответ без choices: {json.dumps(data, ensure_ascii=False)[:500]}")
                raise ValueError(f"API вернул ответ без choices")

            return data["choices"][0]["message"]

        except requests.Timeout:
            log.warning(f"[{room_name}] Timeout (попытка {attempt}/{MAX_RETRIES})")
            last_error = requests.Timeout("API timeout")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAYS[attempt - 1])

        except requests.ConnectionError as e:
            log.warning(f"[{room_name}] Connection error (попытка {attempt}/{MAX_RETRIES}): {e}")
            last_error = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAYS[attempt - 1])

    log.error(f"[{room_name}] Все {MAX_RETRIES} попыток исчерпаны. Последняя ошибка: {last_error}")
    raise last_error


def _call_api_two_images(
    system_prompt: str, user_prompt: str,
    image1_base64: str, image2_base64: str,
    room_name: str = "",
) -> dict:
    """
    Вызов Gemini с ДВУМЯ изображениями (пустая комната + crop схемы).
    Retry логика та же что в _call_api.

    Принимает:
        system_prompt — системный промпт
        user_prompt — юзер-промпт
        image1_base64 — первое изображение (пустая комната)
        image2_base64 — второе изображение (crop схемы с мебелью)
        room_name — для логирования

    Возвращает:
        dict — message из ответа API
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # Два изображения в одном сообщении
    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": user_prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image1_base64}"}},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image2_base64}"}},
        ]
    })

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            log.info(f"[{room_name}] Запрос к Gemini с 2 изображениями (попытка {attempt}/{MAX_RETRIES})")

            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": GEMINI_MODEL,
                    "messages": messages,
                    "temperature": 0,
                },
                timeout=120,
            )

            if response.status_code == 401:
                log.error(f"[{room_name}] API ключ невалидный (401)")
                response.raise_for_status()

            if response.status_code in RETRYABLE_STATUS_CODES:
                log.warning(f"[{room_name}] API {response.status_code}, retry через {RETRY_DELAYS[attempt - 1]} сек")
                last_error = requests.HTTPError(f"HTTP {response.status_code}", response=response)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAYS[attempt - 1])
                continue

            response.raise_for_status()

            data = response.json()
            if "choices" not in data:
                raise ValueError(f"API вернул ответ без choices")

            return data["choices"][0]["message"]

        except requests.Timeout:
            log.warning(f"[{room_name}] Timeout (попытка {attempt}/{MAX_RETRIES})")
            last_error = requests.Timeout("API timeout")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAYS[attempt - 1])

        except requests.ConnectionError as e:
            log.warning(f"[{room_name}] Connection error (попытка {attempt}/{MAX_RETRIES})")
            last_error = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAYS[attempt - 1])

    log.error(f"[{room_name}] Все {MAX_RETRIES} попыток исчерпаны")
    raise last_error


def _extract_image(message: dict, room_name: str = "") -> str:
    """
    Извлекает base64 изображения из ответа Gemini.

    Принимает:
        message — data["choices"][0]["message"] из ответа API
        room_name — для логирования

    Возвращает:
        base64-строка изображения (без data:image/png;base64, префикса)

    Ошибки:
        ValueError — если модель не вернула изображение
    """
    images = message.get("images", [])

    if not images:
        content = message.get("content", "")
        log.error(f"[{room_name}] Gemini не вернул изображение. Текст ответа: {content[:300]}")
        raise ValueError(f"Gemini не сгенерировал изображение. Ответ: {content[:300]}")

    img_url = images[0]["image_url"]["url"]
    if not img_url.startswith("data:"):
        log.error(f"[{room_name}] Неожиданный формат URL: {img_url[:100]}")
        raise ValueError(f"Неожиданный формат изображения: {img_url[:100]}")

    _, b64_data = img_url.split(",", 1)
    log.info(f"[{room_name}] Изображение получено: {len(b64_data) // 1024} KB base64")
    return b64_data
