"""
Слой 3: Горизонтальная генерация стороны комнаты.

Берёт референс (вид сверху из Слоя 2), обрезает нужную сторону,
поворачивает, ставит якоря A/B, отправляет в Gemini Image →
получает горизонтальное фото стены на уровне глаз.

Функции:
    render_side()       — основная: референс + сторона + артефакты → горизонтальное фото
    _call_api()         — вызов Gemini через OpenRouter (с retry до 3 раз)
    _extract_image()    — извлечение base64 из ответа
"""

import requests
import base64
import os
import json
import time

from ..config import OPENROUTER_API_KEY, GEMINI_MODEL
from ..prompts import build_layer3_prompt
from ..logger import get_logger
from .annotate import prepare_for_layer3

log = get_logger("fsk.layer3")

# Настройки retry
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def render_side(reference_path: str, output_path: str, side: str = "top", artifacts: list = None) -> str:
    """
    Генерирует горизонтальное фото одной стороны комнаты.

    Принимает:
        reference_path — путь к референсу из Слоя 2 (вид сверху)
        output_path — путь для сохранения PNG
        side — какую сторону: top/bottom/left/right
        artifacts — артефакты этой стороны из Слоя 2.5 (опционально)

    Выполняет:
        1. Обрезает нужную половину референса
        2. Поворачивает (нужная сторона сверху)
        3. Ставит якоря A, B
        4. Собирает промпт с артефактами
        5. Отправляет в Gemini Image (с retry)
        6. Сохраняет результат

    Возвращает:
        путь к сохранённому изображению

    Ошибки:
        FileNotFoundError — референс не найден
        ValueError — модель не вернула изображение
        requests.HTTPError — API недоступен после 3 попыток
    """
    if not os.path.exists(reference_path):
        raise FileNotFoundError(f"Референс не найден: {reference_path}")

    log.info(f"Генерация стороны {side} | артефактов: {len(artifacts) if artifacts else 0}")

    # Собираем промпт
    system_prompt, user_prompt = build_layer3_prompt(side, artifacts)
    log.info(f"[{side}] Промпт собран")

    # Обрезаем + поворачиваем + якоря
    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)
    prepared_path = os.path.join(output_dir, f"prepared_{side}.png")
    prepare_for_layer3(reference_path, prepared_path, side)
    log.info(f"[{side}] Подготовленное изображение: {prepared_path}")

    # Кодируем
    with open(prepared_path, "rb") as f:
        img_base64 = base64.b64encode(f.read()).decode("utf-8")

    # Вызов API (с retry)
    message = _call_api(system_prompt, user_prompt, img_base64, side)

    # Извлекаем изображение
    image_b64 = _extract_image(message, side)

    # Сохраняем
    img_bytes = base64.b64decode(image_b64)
    with open(output_path, "wb") as f:
        f.write(img_bytes)

    log.info(f"[{side}] Сохранено: {output_path} ({len(img_bytes) // 1024} KB)")
    return output_path


# === ВНУТРЕННИЕ ФУНКЦИИ ===


def _call_api(system_prompt: str, user_prompt: str, img_base64: str, side: str = "") -> dict:
    """
    Вызов Gemini Image через OpenRouter с retry.

    Принимает:
        system_prompt — системный промпт
        user_prompt — юзер-промпт с артефактами
        img_base64 — подготовленное изображение стороны
        side — для логирования

    Retry: до 3 попыток, 1/2/4 сек, retry на 429/5xx/timeout, без retry на 401.

    Возвращает:
        dict — message из ответа API
    """
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
            log.info(f"[{side}] Запрос к Gemini (попытка {attempt}/{MAX_RETRIES})")

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
                log.error(f"[{side}] API ключ невалидный (401)")
                response.raise_for_status()

            # Retryable
            if response.status_code in RETRYABLE_STATUS_CODES:
                log.warning(f"[{side}] API {response.status_code}, retry через {RETRY_DELAYS[attempt - 1]} сек")
                last_error = requests.HTTPError(f"HTTP {response.status_code}", response=response)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAYS[attempt - 1])
                continue

            response.raise_for_status()

            data = response.json()
            if "choices" not in data:
                raise ValueError(f"Ответ без choices: {json.dumps(data, ensure_ascii=False)[:300]}")

            return data["choices"][0]["message"]

        except requests.Timeout:
            log.warning(f"[{side}] Timeout (попытка {attempt}/{MAX_RETRIES})")
            last_error = requests.Timeout("API timeout")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAYS[attempt - 1])

        except requests.ConnectionError as e:
            log.warning(f"[{side}] Connection error (попытка {attempt}/{MAX_RETRIES})")
            last_error = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAYS[attempt - 1])

    log.error(f"[{side}] Все {MAX_RETRIES} попыток исчерпаны")
    raise last_error


def _extract_image(message: dict, side: str = "") -> str:
    """
    Извлекает base64 изображения из ответа Gemini.

    Принимает:
        message — data["choices"][0]["message"]
        side — для логирования

    Возвращает:
        base64-строка (без data:image/png;base64, префикса)

    Ошибки:
        ValueError — модель не вернула изображение
    """
    images = message.get("images", [])

    if not images:
        content = message.get("content", "")
        log.error(f"[{side}] Gemini не вернул изображение. Ответ: {content[:300]}")
        raise ValueError(f"Gemini не сгенерировал изображение. Ответ: {content[:300]}")

    img_url = images[0]["image_url"]["url"]
    if not img_url.startswith("data:"):
        log.error(f"[{side}] Неожиданный формат: {img_url[:100]}")
        raise ValueError(f"Неожиданный формат: {img_url[:100]}")

    _, b64_data = img_url.split(",", 1)
    log.info(f"[{side}] Изображение получено: {len(b64_data) // 1024} KB")
    return b64_data
