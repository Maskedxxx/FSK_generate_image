# Слой 1: Анализ планировки квартиры
# Принимает изображение планировки → возвращает JSON с комнатами, метаданными и вырезанными изображениями

import requests
import base64
import json
import os
from PIL import Image
from ..config import OPENAI_API_KEY, OPENAI_MODEL, LAYER1_TEMPERATURE, LAYER1_IMAGE_DETAIL, OPENROUTER_API_KEY, LAYER1_MODEL
from ..prompts import LAYER1_SYSTEM_PROMPT, LAYER1_ANALYSIS_PROMPT


def analyze_floorplan(image_path: str, output_dir: str = None) -> dict:
    """
    Анализирует планировку квартиры через GPT-4.1 Vision.
    Если указан output_dir — вырезает каждую комнату по bbox и сохраняет.

    Аргументы:
        image_path: путь к изображению планировки (JPG, PNG)
        output_dir: папка для сохранения вырезанных комнат (опционально)

    Возвращает:
        dict с ключами: analysis, rooms[] (+ crop_path для каждой комнаты если output_dir указан)
    """
    # Читаем и кодируем изображение
    img_base64 = _encode_image(image_path)

    # Отправляем в OpenAI API
    raw_response = _call_openai(img_base64)

    # Парсим JSON из ответа
    result = _parse_response(raw_response)

    # Вырезаем комнаты по bbox если указана папка
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        result = _crop_rooms(image_path, result, output_dir)

    return result


def analyze_floorplan_via_osmi(image_path: str) -> dict:
    """
    Анализ через OSMI (Flowise) — OSMI как прокси.
    Промпт формируется на беке, передаётся через разделитель |||
    OSMI-нода просто пробрасывает в OpenAI API.
    """
    from ..config import OSMI_LAYER1_URL

    img_base64 = _encode_image(image_path)

    # Промпт с беке — OSMI просто прокси
    full_prompt = f"{LAYER1_SYSTEM_PROMPT}\n\n{LAYER1_ANALYSIS_PROMPT}"

    response = requests.post(OSMI_LAYER1_URL, json={
        "question": f"{full_prompt}|||{img_base64}"
    })
    response.raise_for_status()

    text = response.json().get("text", "")
    return _parse_response(text)


def _encode_image(image_path: str) -> str:
    """Читает изображение и возвращает base64 строку."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _call_openai(img_base64: str) -> str:
    """Вызов Gemini 3 Flash через OpenRouter для анализа планировки."""
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
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{img_base64}",
                            },
                        },
                    ],
                },
            ],
        },
    )
    response.raise_for_status()

    data = response.json()
    if "choices" not in data:
        raise ValueError(f"API вернул ответ без choices: {data}")

    return data["choices"][0]["message"]["content"]


def _parse_response(text: str) -> dict:
    """Парсит JSON из ответа модели, убирает markdown-обёртку если есть."""
    clean = text.strip()

    # Убираем ```json ... ``` если модель обернула
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1]
        clean = clean.rsplit("```", 1)[0]

    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        raise ValueError(f"Не удалось распарсить JSON из ответа модели: {e}\nОтвет: {clean[:500]}")


def _crop_rooms(image_path: str, analysis: dict, output_dir: str) -> dict:
    """Вырезает каждую комнату из планировки по box_2d координатам (0-1000)."""
    img = Image.open(image_path)
    img_w, img_h = img.size

    for i, room in enumerate(analysis["rooms"]):
        box = room.get("box_2d")
        if not box or len(box) != 4:
            continue

        # box_2d: [y_min, x_min, y_max, x_max] нормализованные 0-1000
        y_min, x_min, y_max, x_max = box

        # Конвертируем в пиксели
        px_x1 = int(x_min / 1000 * img_w)
        px_y1 = int(y_min / 1000 * img_h)
        px_x2 = int(x_max / 1000 * img_w)
        px_y2 = int(y_max / 1000 * img_h)

        # Вырезаем
        crop = img.crop((px_x1, px_y1, px_x2, px_y2))

        # Сохраняем
        room_label = room["name"] if room["name"] != "Nan" else f"room_{room['area']}m2"
        safe_name = room_label.replace(" ", "_").replace("/", "-")
        crop_path = os.path.join(output_dir, f"{i+1}_{safe_name}_crop.png")
        crop.save(crop_path)

        # Добавляем путь в JSON
        room["crop_path"] = crop_path

    return analysis
