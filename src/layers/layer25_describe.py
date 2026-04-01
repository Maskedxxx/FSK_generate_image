"""
Слой 2.5: Описание артефактов по сторонам помещения.

Берёт референс (вид сверху из Слоя 2), режет на 4 стороны,
для каждой спрашивает у Gemini 3 Flash какие артефакты видны →
возвращает JSON с артефактами по сторонам (full/partial).

Функции:
    describe_all_sides()    — основная: референс → артефакты 4 сторон
    _describe_side()        — анализ одной стороны (с retry)
    _call_api()             — вызов Gemini через OpenRouter (с retry до 3 раз)
    _parse_artifacts()      — парсинг JSON из ответа модели
"""

import base64
import json
import os

from ..osmi_client import call_osmi_text
from ..logger import get_logger
from .annotate import prepare_for_layer3

log = get_logger("fsk.layer25")

# Промпты вынесены в prompts.py — но для 2.5 они специфичные, оставляем здесь
DESCRIBE_SYSTEM_PROMPT = """You analyze a cropped section of a room interior (top-down view). The image shows ONE wall of the room with furniture along it. The image is cropped — some items may be only partially visible (cut at the edge).

Your task — list ALL visible elements: furniture, appliances, items, AND also doors, doorways, windows.

Rules:
- Only what is VISIBLE in the image
- Do NOT invent — if not visible, do not list
- Include DOORS/DOORWAYS if visible (even closed doors or passages)
- Include WINDOWS if visible (even if shown as curtains)
- For each element specify visibility: "full" if fully visible, "partial" if cut/partially visible
- Return JSON without markdown wrapping"""

DESCRIBE_USER_TEMPLATE = """Room: {room_name}.
List ALL elements on this image: furniture, appliances, items, doors, doorways, windows.

JSON format:
{{"artifacts": [{{"name": "element name", "visibility": "full or partial"}}]}}"""


def describe_all_sides(reference_path: str, room: dict, output_dir: str) -> dict:
    """
    Описывает артефакты всех 4 сторон помещения.

    Принимает:
        reference_path — путь к референсу из Слоя 2
        room — метаданные комнаты из Слоя 1 {name, area, ...}
        output_dir — папка для сохранения подготовленных изображений сторон

    Выполняет:
        Для каждой стороны (top/bottom/left/right):
        1. Обрезает половину референса
        2. Поворачивает (нужная сторона сверху)
        3. Ставит якоря A, B
        4. Отправляет в Gemini → получает список артефактов

    Возвращает:
        dict {top: [...], bottom: [...], left: [...], right: [...]}
        Каждый элемент: {name: str, visibility: "full"/"partial"}

    Ошибки:
        FileNotFoundError — референс не найден
    """
    if not os.path.exists(reference_path):
        raise FileNotFoundError(f"Референс не найден: {reference_path}")

    os.makedirs(output_dir, exist_ok=True)
    room_name = room["name"] if room["name"] != "Nan" else f"Room {room['area']} sq.m"

    log.info(f"[{room_name}] Описание артефактов по 4 сторонам")

    sides_artifacts = {}

    for side in ["top", "bottom", "left", "right"]:
        log.info(f"[{room_name}] Анализ стороны {side}...")

        # Обрезаем и поворачиваем сторону
        prepared_path = os.path.join(output_dir, f"side_{side}.png")
        prepare_for_layer3(reference_path, prepared_path, side)

        # Описываем артефакты
        artifacts = _describe_side(prepared_path, room_name, side)
        sides_artifacts[side] = artifacts

        log.info(f"[{room_name}] {side}: {len(artifacts)} артефактов")

    # Сохраняем JSON
    json_path = os.path.join(output_dir, "sides_artifacts.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(sides_artifacts, f, indent=2, ensure_ascii=False)

    log.info(f"[{room_name}] Артефакты сохранены: {json_path}")
    return sides_artifacts


def _describe_side(image_path: str, room_name: str, side: str) -> list:
    """
    Анализирует одну сторону через OSMI-ноду FSK_Layer1_TextAnalysis.

    Принимает:
        image_path — путь к подготовленному изображению стороны
        room_name — имя комнаты
        side — название стороны

    Возвращает:
        список артефактов [{name, visibility}, ...]
        Пустой список при ошибке
    """
    # Кодируем изображение
    with open(image_path, "rb") as f:
        img_base64 = base64.b64encode(f.read()).decode("utf-8")

    user_prompt = DESCRIBE_USER_TEMPLATE.format(room_name=room_name)
    prompt = f"{DESCRIBE_SYSTEM_PROMPT}\n\n{user_prompt}"

    # Вызов OSMI текстовой ноды
    try:
        response_text = call_osmi_text(prompt, img_base64, f"{room_name}/{side}")
    except Exception as e:
        log.error(f"[{room_name}] {side}: OSMI ошибка — {e}")
        return []

    # Парсим артефакты
    artifacts = _parse_artifacts(response_text, f"{room_name}/{side}")
    return artifacts


def _parse_artifacts(text: str, context: str = "") -> list:
    """
    Парсит JSON с артефактами из ответа модели.

    Принимает:
        text — сырой текст ответа
        context — для логирования

    Возвращает:
        список артефактов [{name, visibility}, ...]
        Пустой список при ошибке парсинга
    """
    if not text or not text.strip():
        log.warning(f"[{context}] Пустой ответ от модели")
        return []

    clean = text.strip()

    # Убираем markdown-обёртку
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1]
        clean = clean.rsplit("```", 1)[0]

    try:
        parsed = json.loads(clean)
        artifacts = parsed.get("artifacts", [])
        log.info(f"[{context}] Распарсено: {len(artifacts)} артефактов")
        return artifacts
    except json.JSONDecodeError as e:
        log.error(f"[{context}] Ошибка парсинга JSON: {e}\nОтвет: {text[:300]}")
        return []
