# Слой 3: Генерация горизонтального вида конкретной стороны комнаты
# Принимает референс (вид сверху из Слоя 2) + сторону → горизонтальное фото

import requests
import base64
from ..config import OPENROUTER_API_KEY, GEMINI_MODEL
from ..prompts import build_layer3_prompt


def render_side(reference_path: str, output_path: str, side: str = "right") -> str:
    """
    Генерирует горизонтальное фото одной стороны комнаты по референсу.

    Аргументы:
        reference_path: путь к референс-изображению (вид сверху из Слоя 2)
        output_path: путь для сохранения финального PNG
        side: какую сторону генерировать — top/bottom/left/right

    Возвращает:
        путь к сохранённому изображению
    """
    system_prompt, user_prompt = build_layer3_prompt(side)

    # Печатаем полный промпт
    print(f"\n=== SYSTEM PROMPT ===\n{system_prompt}")
    print(f"\n=== USER PROMPT ===\n{user_prompt}\n")

    with open(reference_path, "rb") as f:
        img_base64 = base64.b64encode(f.read()).decode("utf-8")

    image_b64 = _call_gemini(system_prompt, user_prompt, img_base64)

    img_bytes = base64.b64decode(image_b64)
    with open(output_path, "wb") as f:
        f.write(img_bytes)

    return output_path


def _call_gemini(system_prompt: str, user_prompt: str, img_base64: str) -> str:
    """Вызов Gemini с референсом. Возвращает base64 сгенерированной картинки."""
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
