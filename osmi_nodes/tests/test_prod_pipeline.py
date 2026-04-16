"""
Тест боевого OSMI пайплайна с guard-роутером.

Два кейса:
1. Валидный план + реальный опросник → полный пайплайн L1-L4 (~150 сек, ~$0.5-1)
2. Невалидное изображение → отсечение на guard (~3 сек, $0)

python osmi_nodes/tests/test_prod_pipeline.py
"""

import base64
import json
import time
from pathlib import Path

import requests

PROD_URL = "https://app.osmi-ai.ru/api/v1/prediction/c3ab4cc3-3212-4863-ae99-a3b7e6efd00b"
FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Полный опросник — пример из questionnaire.json
ANSWERS = {
    "style": "Скандинавский",
    "colors": "Светлые (белый, беж, серый)",
    "materials": ["Натуральное дерево", "Текстиль (лен, хлопок, бархат, шерсть)"],
    "residents": "2 взрослых без детей",
    "work_from_home": "Да, но достаточно рабочего угла",
    "hobby": "Чтение и коллекционирование (полки, библиотека, кресло)",
    "bathroom_layout": "Совмещённый санузел",
    "bath_type": "Душевая",
    "storage": ["Чемоданы"]
}


def call_pipeline(image_base64, answers_json, name, timeout=300):
    """Отправляет запрос в боевой пайплайн и печатает результат."""
    question = f"{image_base64}|||{answers_json}"
    print(f"\n{'='*60}\n  {name}\n{'='*60}")
    t0 = time.monotonic()
    try:
        r = requests.post(PROD_URL, json={"question": question}, timeout=timeout)
        dt = round(time.monotonic() - t0, 1)
        print(f"HTTP {r.status_code} — {dt}s")
        body = r.json()
        text = body.get("text", json.dumps(body))
        # Пытаемся распарсить как JSON для красивого вывода
        try:
            result = json.loads(text) if isinstance(text, str) else text
            # Если ответ большой (полный пайплайн) — показываем ключевые поля
            if isinstance(result, dict) and "task_id" in result:
                print(f"task_id: {result.get('task_id')}")
                print(f"Ключи ответа: {list(result.keys())}")
                # crops и composite если есть
                if "crops" in result:
                    print(f"Crops: {len(result['crops'])}")
                if "composite_s3_key" in result:
                    print(f"Composite: {result['composite_s3_key']}")
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False)[:2000])
        except Exception:
            print(text[:2000] if isinstance(text, str) else str(body)[:2000])
    except requests.Timeout:
        dt = round(time.monotonic() - t0, 1)
        print(f"TIMEOUT после {dt}s")
    except Exception as e:
        print(f"ERROR: {e}")


def main():
    # ТЕСТ 1: валидный план + реальный опросник → полный пайплайн
    plan_path = FIXTURES_DIR / "test_plan.jpg"
    with open(plan_path, "rb") as f:
        plan_b64 = base64.b64encode(f.read()).decode()
    answers_json = json.dumps(ANSWERS, ensure_ascii=False)
    call_pipeline(
        plan_b64,
        answers_json,
        "ТЕСТ 1: валидная планировка + опросник (полный пайплайн ~150s)",
        timeout=300
    )

    # ТЕСТ 2: невалидное изображение → guard должен отсечь
    tiny_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
    call_pipeline(
        tiny_png,
        "{}",
        "ТЕСТ 2: невалидное изображение (ожидаем отказ от guard)",
        timeout=30
    )


if __name__ == "__main__":
    main()
