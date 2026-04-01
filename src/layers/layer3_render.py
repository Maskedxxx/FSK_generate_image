"""
Слой 3: Горизонтальная генерация стороны комнаты.

Берёт референс (вид сверху из Слоя 2), обрезает нужную сторону,
поворачивает, ставит якоря A/B, отправляет через OSMI-ноду FSK_Layer2_ImageGen →
получает горизонтальное фото стены на уровне глаз.

Функции:
    render_side()       — основная: референс + сторона + артефакты → горизонтальное фото
"""

import base64
import os

from ..prompts import build_layer3_prompt
from ..osmi_client import call_osmi_image
from ..logger import get_logger
from .annotate import prepare_for_layer3

log = get_logger("fsk.layer3")


def render_side(reference_path: str, output_path: str, side: str = "top", artifacts: list = None) -> str:
    """
    Генерирует горизонтальное фото одной стороны комнаты через OSMI.

    Принимает:
        reference_path — путь к референсу из Слоя 2 (вид сверху)
        output_path — путь для сохранения PNG
        side — какую сторону: top/bottom/left/right
        artifacts — артефакты этой стороны из Слоя 2.5 (опционально)

    Выполняет:
        1. Обрезает нужную половину референса
        2. Поворачивает (нужная сторона сверху)
        3. Ставит якоря A, B
        4. Отправляет через OSMI-ноду FSK_Layer2_ImageGen

    Возвращает:
        путь к сохранённому изображению
    """
    if not os.path.exists(reference_path):
        raise FileNotFoundError(f"Референс не найден: {reference_path}")

    log.info(f"Генерация стороны {side} | артефактов: {len(artifacts) if artifacts else 0}")

    # Собираем промпт
    system_prompt, user_prompt = build_layer3_prompt(side, artifacts)
    prompt = f"{system_prompt}\n\n{user_prompt}"
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

    # Вызов OSMI-ноды FSK_Layer2_ImageGen (1 изображение)
    image_b64 = call_osmi_image(prompt, img_base64, f"layer3/{side}")

    # Сохраняем
    img_bytes = base64.b64decode(image_b64)
    with open(output_path, "wb") as f:
        f.write(img_bytes)

    log.info(f"[{side}] Сохранено: {output_path} ({len(img_bytes) // 1024} KB)")
    return output_path
