"""
Мок пайплайна — подменяет run_pipeline для тестов API.

Не вызывает реальные API (OpenRouter, Gemini).
Возвращает фейковый результат с задержкой для тестирования прогресса.

Использование:
    В тестах через monkeypatch:
        monkeypatch.setattr("src.api.run_pipeline", mock_run_pipeline)
"""

import time
from typing import Callable


def mock_run_pipeline(
    image_path: str,
    answers: dict,
    output_dir: str,
    on_progress: Callable[[str], None] = None,
) -> dict:
    """
    Мок пайплайна — имитирует работу без вызова API.

    Принимает:
        image_path — путь к изображению (не используется)
        answers — ответы опросника (не используются)
        output_dir — папка результатов (не используется)
        on_progress — колбэк прогресса

    Возвращает:
        фейковый результат с 2 комнатами
    """
    if on_progress:
        on_progress("Слой 1: анализ планировки...")

    # Имитация задержки обработки
    time.sleep(0.1)

    if on_progress:
        on_progress("Слой 2: генерация Кухня-гостиная (1/2)...")

    time.sleep(0.1)

    if on_progress:
        on_progress("Готово")

    return {
        "rooms_count": 2,
        "rooms": [
            {
                "name": "Кухня-гостиная",
                "area": 17.7,
                "shape": "прямоугольная",
                "reference": f"{output_dir}/layer2/Кухня-гостиная_reference.png",
                "sides": {
                    "top": f"{output_dir}/layer3/Кухня-гостиная/top.png",
                    "bottom": f"{output_dir}/layer3/Кухня-гостиная/bottom.png",
                    "left": f"{output_dir}/layer3/Кухня-гостиная/left.png",
                    "right": f"{output_dir}/layer3/Кухня-гостиная/right.png",
                },
            },
            {
                "name": "Спальня",
                "area": 14.8,
                "shape": "прямоугольная",
                "reference": f"{output_dir}/layer2/Спальня_reference.png",
                "sides": {
                    "top": f"{output_dir}/layer3/Спальня/top.png",
                    "bottom": f"{output_dir}/layer3/Спальня/bottom.png",
                    "left": f"{output_dir}/layer3/Спальня/left.png",
                    "right": f"{output_dir}/layer3/Спальня/right.png",
                },
            },
        ],
    }


def mock_run_pipeline_slow(
    image_path: str,
    answers: dict,
    output_dir: str,
    on_progress: Callable[[str], None] = None,
) -> dict:
    """
    Медленный мок — для тестирования статуса processing.
    Спит 2 секунды перед возвратом результата.
    """
    if on_progress:
        on_progress("Слой 1: анализ планировки...")

    time.sleep(2)

    if on_progress:
        on_progress("Готово")

    return mock_run_pipeline(image_path, answers, output_dir, on_progress=None)
