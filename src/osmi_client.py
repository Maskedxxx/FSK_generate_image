"""
Клиент для вызова OSMI-нод (Flowise).

Все слои обращаются к AI-моделям через OSMI-ноды (JS-прокси).
Формат: промпт|||base64_image1[|||base64_image2]

Функции:
    call_osmi_text()    — вызов текстовой ноды (Слой 1, 2.5) → текст
    call_osmi_image()   — вызов ноды генерации с 1 изображением (Слой 2 pass1, Слой 3) → base64
    call_osmi_image_dual() — вызов ноды генерации с 2 изображениями (Слой 2 pass2) → base64
"""

import requests
import json
import time

from .config import OSMI_LAYER1_URL, OSMI_LAYER2_URL, OSMI_LAYER2_DUAL_URL
from .logger import get_logger

log = get_logger("fsk.osmi")

# Настройки retry
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def call_osmi_text(prompt: str, img_base64: str = "", context: str = "") -> str:
    """
    Вызов текстовой ноды OSMI (FSK_Layer1_TextAnalysis).
    Используется Слоем 1 и Слоем 2.5.

    Принимает:
        prompt — текстовый промпт (system + user)
        img_base64 — изображение в base64 (опционально)
        context — для логирования

    Возвращает:
        текст ответа модели

    Ошибки:
        ValueError — нода вернула ошибку или пустой ответ
        requests.HTTPError — после 3 попыток
    """
    # Формируем payload: промпт|||base64
    question = f"{prompt}|||{img_base64}" if img_base64 else prompt
    return _call_osmi(OSMI_LAYER1_URL, question, context, extract_type="text")


def call_osmi_image(prompt: str, img_base64: str = "", context: str = "") -> str:
    """
    Вызов ноды генерации с 1 изображением (FSK_Layer2_ImageGen).
    Используется Слоем 2 (Проход 1) и Слоем 3.

    Принимает:
        prompt — промпт
        img_base64 — изображение в base64
        context — для логирования

    Возвращает:
        base64 сгенерированного изображения (без data:image/png;base64, префикса)
    """
    question = f"{prompt}|||{img_base64}" if img_base64 else prompt
    return _call_osmi(OSMI_LAYER2_URL, question, context, extract_type="image")


def call_osmi_image_dual(prompt: str, img1_base64: str, img2_base64: str, context: str = "") -> str:
    """
    Вызов ноды генерации с 2 изображениями (FSK_Layer2_ImageGen_Dual).
    Используется Слоем 2 (Проход 2).

    Принимает:
        prompt — промпт
        img1_base64 — первое изображение (пустая комната)
        img2_base64 — второе изображение (crop схемы)
        context — для логирования

    Возвращает:
        base64 сгенерированного изображения
    """
    question = f"{prompt}|||{img1_base64}|||{img2_base64}"
    return _call_osmi(OSMI_LAYER2_DUAL_URL, question, context, extract_type="image")


# === ВНУТРЕННИЕ ФУНКЦИИ ===


def _call_osmi(url: str, question: str, context: str, extract_type: str) -> str:
    """
    Общий вызов OSMI-ноды с retry.

    Принимает:
        url — URL ноды
        question — payload (промпт|||base64)
        context — для логирования
        extract_type — "text" (вернуть текст) или "image" (извлечь base64 из markdown)

    Возвращает:
        текст или base64 изображения
    """
    if not url:
        raise ValueError(f"[{context}] OSMI URL не задан. Проверьте .env")

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            log.info(f"[{context}] Запрос к OSMI (попытка {attempt}/{MAX_RETRIES})")

            response = requests.post(
                url,
                json={"question": question},
                timeout=120,
            )

            # Retryable статусы
            if response.status_code in RETRYABLE_STATUS_CODES:
                log.warning(f"[{context}] OSMI {response.status_code}, retry через {RETRY_DELAYS[attempt - 1]} сек")
                last_error = requests.HTTPError(f"HTTP {response.status_code}", response=response)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAYS[attempt - 1])
                continue

            response.raise_for_status()

            data = response.json()
            text = data.get("text", "")

            # OSMI может разложить JSON ответ модели по отдельным полям
            # Вместо строки в "text" — поля в корне ответа
            # Собираем обратно в JSON строку если обнаружили наши поля
            osmi_meta_keys = {"question", "chatId", "chatMessageId", "isStreamValid", "sessionId", "text"}
            model_keys = set(data.keys()) - osmi_meta_keys

            if not text and model_keys:
                # Есть поля от модели — собираем JSON из них
                reconstructed = {k: data[k] for k in model_keys if k in data}
                text = json.dumps(reconstructed, ensure_ascii=False)
                log.info(f"[{context}] OSMI разложил JSON по полям ({list(model_keys)}) — собрали обратно")

            if not text:
                raw_preview = json.dumps(data, ensure_ascii=False)[:500]
                log.warning(f"[{context}] OSMI пустой ответ (попытка {attempt}/{MAX_RETRIES}). Сырой ответ: {raw_preview}")
                last_error = ValueError(f"OSMI вернул пустой ответ. Сырой: {raw_preview}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAYS[attempt - 1])
                continue

            # Проверяем на ошибку от JS-ноды
            if text.startswith('{"error"'):
                try:
                    err = json.loads(text)
                    raise ValueError(f"OSMI нода ошибка: {err.get('error', text)}")
                except json.JSONDecodeError:
                    pass

            log.info(f"[{context}] Ответ OSMI: {len(text)} символов")

            # Извлекаем результат
            if extract_type == "image":
                return _extract_image_from_markdown(text, context)
            else:
                return text

        except requests.Timeout:
            log.warning(f"[{context}] Timeout (попытка {attempt}/{MAX_RETRIES})")
            last_error = requests.Timeout("OSMI timeout")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAYS[attempt - 1])

        except requests.ConnectionError as e:
            log.warning(f"[{context}] Connection error (попытка {attempt}/{MAX_RETRIES})")
            last_error = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAYS[attempt - 1])

    log.error(f"[{context}] Все {MAX_RETRIES} попыток исчерпаны")
    raise last_error


def _extract_image_from_markdown(text: str, context: str) -> str:
    """
    Извлекает base64 из markdown формата ![...](data:image/...;base64,...).

    Принимает:
        text — текст ответа OSMI
        context — для логирования

    Возвращает:
        base64 строка (без префикса data:image/...)
    """
    if "![" not in text:
        log.error(f"[{context}] OSMI не вернул изображение. Ответ: {text[:300]}")
        raise ValueError(f"OSMI не вернул изображение. Ответ: {text[:300]}")

    start = text.index("(") + 1
    end = text.index(")")
    img_url = text[start:end]

    if not img_url.startswith("data:"):
        raise ValueError(f"Неожиданный формат: {img_url[:100]}")

    _, b64_data = img_url.split(",", 1)
    log.info(f"[{context}] Изображение: {len(b64_data) // 1024} KB")
    return b64_data
