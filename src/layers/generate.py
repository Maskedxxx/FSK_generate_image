# Слой 2: Генерация визуализации комнаты
# Принимает вырезанную схему комнаты + ответы опросника → изображение

import requests
import base64
from ..config import OPENROUTER_API_KEY, GEMINI_MODEL
from ..prompts import build_layer2_prompt


def generate_room(room: dict, answers: dict, crop_path: str, output_path: str) -> str:
    """
    Генерирует визуализацию комнаты через Gemini.
    Передаёт ВЫРЕЗАННУЮ схему комнаты (crop) + промпт из опросника.

    Аргументы:
        room: метаданные комнаты из Слоя 1 {name, area, shape, crop_path, ...}
        answers: ответы опросника {style, colors, materials, ...}
        crop_path: путь к вырезанному изображению комнаты
        output_path: путь для сохранения сгенерированного PNG

    Возвращает:
        путь к сохранённому изображению
    """
    # Собираем промпты
    system_prompt, user_prompt = build_layer2_prompt(room, answers)

    # Кодируем вырезанную схему в base64
    with open(crop_path, "rb") as f:
        img_base64 = base64.b64encode(f.read()).decode("utf-8")

    # Отправляем в Gemini
    image_b64 = _call_gemini(system_prompt, user_prompt, img_base64)

    # Сохраняем результат
    img_bytes = base64.b64decode(image_b64)
    with open(output_path, "wb") as f:
        f.write(img_bytes)

    return output_path


def _call_gemini(system_prompt: str, user_prompt: str, img_base64: str) -> str:
    """Вызов Gemini через OpenRouter. Возвращает base64 сгенерированной картинки."""
    messages = []

    # Системный промпт (если не пустой)
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # Юзер-промпт + вырезанная схема комнаты
    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": user_prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_base64}"}}
        ]
    })

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": GEMINI_MODEL,
            "messages": messages,
        },
    )
    response.raise_for_status()

    data = response.json()
    message = data["choices"][0]["message"]
    images = message.get("images", [])

    if not images:
        raise ValueError(f"Gemini не сгенерировал изображение. content: {message.get('content', '')[:300]}")

    img_url = images[0]["image_url"]["url"]
    if not img_url.startswith("data:"):
        raise ValueError(f"Неожиданный формат: {img_url[:100]}")

    _, b64_data = img_url.split(",", 1)
    return b64_data
