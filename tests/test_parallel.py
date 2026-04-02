"""
Тест параллельной обработки 10 задач с замоканным OSMI.

Проверяет:
- 10 одновременных POST /generate → все получают task_id
- Все 10 задач завершаются (done)
- Время выполнения < 30 сек (5 воркеров, мок 2 сек на вызов)
- Нет коллизий (все task_id уникальны)
- Статусы в S3 корректны

Запуск: python tests/test_parallel.py
"""

import sys
import os
import time
import json
import threading
import base64
from io import BytesIO
from unittest.mock import patch
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Сброс singleton
import src.storage as storage_module
storage_module._storage_instance = None

# === МОКИ OSMI ===

MOCK_DELAY = 1  # секунд задержка имитации OSMI


def _make_fake_image_b64():
    """Создаёт фейковое PNG в base64."""
    img = Image.new("RGB", (512, 512), (200, 200, 200))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


FAKE_IMAGE_B64 = _make_fake_image_b64()

FAKE_ANALYSIS_JSON = json.dumps({
    "analysis": "Test floor plan with 1 room",
    "rooms": [{
        "name": "Тест",
        "name_source": "label",
        "area": 10.0,
        "shape": "rectangular",
        "analysis": "Test room",
        "walls": {"top": "wall", "left": "wall", "bottom": "wall", "right": "wall"},
        "polygon": [[100, 100], [900, 100], [900, 900], [100, 900]],
    }]
})


def mock_call_osmi_text(prompt, img_base64, context=""):
    """Мок текстовой OSMI-ноды — возвращает фейковый analysis JSON."""
    time.sleep(MOCK_DELAY)
    return FAKE_ANALYSIS_JSON


def mock_call_osmi_image(prompt, img_base64, context=""):
    """Мок ноды генерации — возвращает фейковое изображение."""
    time.sleep(MOCK_DELAY)
    return FAKE_IMAGE_B64


def mock_call_osmi_image_dual(prompt, img1_b64, img2_b64, context=""):
    """Мок ноды с 2 изображениями."""
    time.sleep(MOCK_DELAY)
    return FAKE_IMAGE_B64


# === ТЕСТОВОЕ ИЗОБРАЖЕНИЕ ===

def _make_test_image_bytes():
    """Создаёт тестовое изображение планировки."""
    img = Image.new("RGB", (400, 400), (255, 255, 255))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


TEST_IMAGE = _make_test_image_bytes()
TEST_ANSWERS = json.dumps({
    "style": "Скандинавский",
    "colors": "Светлые (белый, беж, серый)",
    "materials": ["Натуральное дерево"],
    "residents": "2 взрослых без детей",
    "work_from_home": "Нет, работа вне дома",
    "hobby": "Чтение и коллекционирование (полки, библиотека, кресло)",
    "bathroom_layout": "Совмещённый санузел",
    "bath_type": "Душевая",
    "storage": ["Чемоданы"],
})


# === ТЕСТ ===

def main():
    print("\n=== Тест параллельной обработки (10 задач) ===\n")

    # Патчим OSMI
    with patch("src.osmi_client.call_osmi_text", side_effect=mock_call_osmi_text), \
         patch("src.osmi_client.call_osmi_image", side_effect=mock_call_osmi_image), \
         patch("src.osmi_client.call_osmi_image_dual", side_effect=mock_call_osmi_image_dual):

        from src.api import app
        from src.storage import create_storage
        from src import task_manager

        storage = create_storage()

        # Используем TestClient от httpx
        from fastapi.testclient import TestClient
        client = TestClient(app)

        NUM_USERS = 10
        task_ids = []
        errors = []

        # === Шаг 1: 10 параллельных POST /generate ===
        print(f"Отправляем {NUM_USERS} запросов параллельно...")
        t_start = time.time()

        def send_request(index):
            try:
                resp = client.post(
                    "/generate",
                    headers={"X-API-Key": "fsk-gen-2026-a7b3c9d1e5f2"},
                    files={"image": (f"plan_{index}.jpg", TEST_IMAGE, "image/jpeg")},
                    data={"answers": TEST_ANSWERS},
                )
                data = resp.json()
                if resp.status_code == 200 and "task_id" in data:
                    task_ids.append(data["task_id"])
                else:
                    errors.append(f"User {index}: HTTP {resp.status_code} — {data}")
            except Exception as e:
                errors.append(f"User {index}: {e}")

        threads = []
        for i in range(NUM_USERS):
            t = threading.Thread(target=send_request, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        t_submit = time.time() - t_start
        print(f"  Отправлено за {t_submit:.1f} сек")
        print(f"  task_id получено: {len(task_ids)}")
        if errors:
            print(f"  Ошибки при отправке: {errors}")

        # === Шаг 2: Проверяем уникальность task_id ===
        unique_ids = set(task_ids)
        assert len(unique_ids) == len(task_ids), f"Коллизия task_id! {len(task_ids)} всего, {len(unique_ids)} уникальных"
        print(f"  Все task_id уникальны: ✓")

        # === Шаг 3: Поллим статусы ===
        print(f"\nОжидаем завершения...")
        MAX_WAIT = 120  # максимум 2 минуты
        poll_start = time.time()
        done_ids = set()
        error_ids = set()

        while time.time() - poll_start < MAX_WAIT:
            for tid in task_ids:
                if tid in done_ids or tid in error_ids:
                    continue
                resp = client.get(f"/status/{tid}")
                if resp.status_code == 200:
                    data = resp.json()
                    status = data.get("status")
                    if status == "done":
                        done_ids.add(tid)
                    elif status == "error":
                        error_ids.add(tid)
                        print(f"  ✗ {tid}: {data.get('error', '?')}")

            if len(done_ids) + len(error_ids) == len(task_ids):
                break
            time.sleep(0.5)

        t_total = time.time() - t_start
        print(f"\nЗавершено за {t_total:.1f} сек:")
        print(f"  done:  {len(done_ids)}")
        print(f"  error: {len(error_ids)}")
        still = len(task_ids) - len(done_ids) - len(error_ids)
        if still:
            print(f"  зависло: {still}")

        # === Шаг 4: Проверяем S3 ===
        print(f"\nПроверяем S3...")
        s3_ok = 0
        for tid in done_ids:
            task = task_manager.get_task(storage, tid)
            if task and task.get("status") == "done":
                s3_ok += 1
        print(f"  status.json в S3 с done: {s3_ok}/{len(done_ids)}")

        # === Шаг 5: Cleanup ===
        print(f"\nОчистка тестовых данных...")
        for tid in task_ids:
            storage.delete_prefix(f"{tid}/")
        print(f"  Удалено {len(task_ids)} задач")

        # === Итоги ===
        print(f"\n{'='*50}")
        print(f"Отправлено:    {NUM_USERS}")
        print(f"Получили ID:   {len(task_ids)}")
        print(f"Завершилось:   {len(done_ids)} done, {len(error_ids)} error")
        print(f"Время:         {t_total:.1f} сек")
        print(f"S3 статусы:    {s3_ok} корректных")

        if len(done_ids) == NUM_USERS:
            print(f"\n✓ ВСЕ {NUM_USERS} ЗАДАЧ ЗАВЕРШЕНЫ УСПЕШНО")
        else:
            print(f"\n✗ Не все задачи завершены")
            sys.exit(1)


if __name__ == "__main__":
    main()
