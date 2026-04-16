"""
Быстрый тест guard-ноды на OSMI.

python osmi_nodes/tests/test_guard.py
"""

import base64
import json
import os
import sys
import time
from pathlib import Path

import requests

GUARD_URL = "https://app.osmi-ai.ru/api/v1/prediction/726f5642-5039-431d-94b3-4032031cf4b6"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def call_guard(image_base64, name):
    """Отправляет картинку в guard-флоу и печатает результат."""
    question = f"{image_base64}|||{{}}"
    print(f"\n{'='*60}\n  {name}\n{'='*60}")
    t0 = time.monotonic()
    try:
        r = requests.post(GUARD_URL, json={"question": question}, timeout=90)
        dt = round(time.monotonic() - t0, 1)
        print(f"HTTP {r.status_code} — {dt}s")
        # OSMI оборачивает ответ — парсим
        body = r.json()
        # Ищем наш guard-объект в ответе
        text = body.get("text", json.dumps(body))
        try:
            result = json.loads(text) if isinstance(text, str) else text
            print(json.dumps(result, indent=2, ensure_ascii=False))
        except Exception:
            print(text[:2000])
    except Exception as e:
        print(f"ERROR: {e}")


def main():
    # ТЕСТ 1: валидная планировка
    plan_path = FIXTURES_DIR / "test_plan.jpg"
    with open(plan_path, "rb") as f:
        plan_b64 = base64.b64encode(f.read()).decode()
    call_guard(plan_b64, "ТЕСТ 1: валидная планировка (test_plan.jpg)")

    # ТЕСТ 2: пустое/минимальное изображение (1x1 красный PNG)
    tiny_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
    call_guard(tiny_png, "ТЕСТ 2: пустое изображение (1x1 PNG)")


if __name__ == "__main__":
    main()
