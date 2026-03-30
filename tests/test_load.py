"""
Нагрузочный тест — 50 одновременных запросов к POST /generate.

По ТЗ: ≥50 пользователей одновременно, деградация не более 20%.

Проверяем:
    - Все 50 запросов получили task_id (без ошибок)
    - Время ответа каждого
    - Среднее, медианное, максимальное время
    - Деградация: среднее при 50 vs среднее при 1

Запуск:
    1. Поднять сервер: uvicorn src.api:app --reload
    2. python tests/test_load.py

Или с моком (без реального сервера):
    python tests/test_load.py --mock
"""

import asyncio
import time
import sys
import os
import json
import statistics
from io import BytesIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Параметры теста
CONCURRENT_USERS = 50
SERVER_URL = "http://localhost:8000"
from src.config import FSK_API_KEY
API_KEY = FSK_API_KEY
MAX_DEGRADATION_PERCENT = 20  # по ТЗ

# Тестовые данные
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


def make_fake_image() -> bytes:
    """Создаёт минимальный JPG для теста."""
    return b"\xff\xd8\xff\xe0" + b"\x00" * 1024


async def single_request(client, user_id: int) -> dict:
    """
    Один запрос POST /generate. Возвращает результат с таймингом.
    """
    import httpx

    image_data = make_fake_image()
    start = time.perf_counter()

    try:
        r = await client.post(
            f"{SERVER_URL}/generate",
            files={"image": (f"plan_{user_id}.jpg", BytesIO(image_data), "image/jpeg")},
            data={"answers": TEST_ANSWERS},
            headers={"X-API-Key": API_KEY},
            timeout=30.0,
        )
        elapsed = time.perf_counter() - start

        return {
            "user_id": user_id,
            "status_code": r.status_code,
            "elapsed": elapsed,
            "task_id": r.json().get("task_id", None) if r.status_code == 200 else None,
            "error": r.json().get("error", None) if r.status_code != 200 else None,
        }
    except Exception as e:
        elapsed = time.perf_counter() - start
        return {
            "user_id": user_id,
            "status_code": 0,
            "elapsed": elapsed,
            "task_id": None,
            "error": str(e),
        }


async def run_load_test():
    """Запускает нагрузочный тест."""
    import httpx

    print(f"=== Нагрузочный тест: {CONCURRENT_USERS} одновременных запросов ===")
    print(f"Сервер: {SERVER_URL}")
    print()

    # Шаг 1: Замер базовой скорости (1 запрос)
    print("Шаг 1: Замер базовой скорости (1 запрос)...")
    async with httpx.AsyncClient() as client:
        baseline = await single_request(client, 0)

    if baseline["status_code"] != 200:
        print(f"❌ Базовый запрос упал: {baseline['status_code']} {baseline['error']}")
        print("Убедитесь что сервер запущен: uvicorn src.api:app --reload")
        return

    baseline_time = baseline["elapsed"]
    print(f"✅ Базовое время: {baseline_time:.3f} сек")
    print()

    # Шаг 2: 50 одновременных запросов
    print(f"Шаг 2: {CONCURRENT_USERS} одновременных запросов...")
    start_total = time.perf_counter()

    async with httpx.AsyncClient() as client:
        tasks = [single_request(client, i + 1) for i in range(CONCURRENT_USERS)]
        results = await asyncio.gather(*tasks)

    total_time = time.perf_counter() - start_total

    # Шаг 3: Анализ результатов
    print()
    print("=== РЕЗУЛЬТАТЫ ===")
    print()

    # Успешные / неуспешные
    success = [r for r in results if r["status_code"] == 200]
    failed = [r for r in results if r["status_code"] != 200]

    print(f"Запросов: {len(results)}")
    print(f"✅ Успешных: {len(success)}")
    print(f"❌ Неуспешных: {len(failed)}")

    if failed:
        print(f"\nОшибки:")
        for f in failed[:5]:
            print(f"  user {f['user_id']}: {f['status_code']} — {f['error']}")
        if len(failed) > 5:
            print(f"  ... и ещё {len(failed) - 5}")

    if not success:
        print("\n❌ Ни один запрос не прошёл!")
        return

    # Тайминги
    times = [r["elapsed"] for r in success]
    avg_time = statistics.mean(times)
    median_time = statistics.median(times)
    min_time = min(times)
    max_time = max(times)
    p95_time = sorted(times)[int(len(times) * 0.95)]

    print(f"\nТайминги (время ответа POST /generate):")
    print(f"  Среднее:  {avg_time:.3f} сек")
    print(f"  Медиана:  {median_time:.3f} сек")
    print(f"  Мин:      {min_time:.3f} сек")
    print(f"  Макс:     {max_time:.3f} сек")
    print(f"  P95:      {p95_time:.3f} сек")
    print(f"  Общее:    {total_time:.3f} сек на {CONCURRENT_USERS} запросов")

    # Деградация
    degradation = ((avg_time - baseline_time) / baseline_time) * 100 if baseline_time > 0 else 0
    print(f"\nДеградация:")
    print(f"  Базовое (1 запрос):     {baseline_time:.3f} сек")
    print(f"  Среднее ({CONCURRENT_USERS} запросов): {avg_time:.3f} сек")
    print(f"  Деградация:             {degradation:.1f}%")

    if degradation <= MAX_DEGRADATION_PERCENT:
        print(f"  ✅ В пределах нормы (≤{MAX_DEGRADATION_PERCENT}% по ТЗ)")
    else:
        print(f"  ⚠️ Превышает норму ({MAX_DEGRADATION_PERCENT}% по ТЗ)")

    # Пропускная способность
    rps = len(success) / total_time
    per_hour = rps * 3600
    print(f"\nПропускная способность:")
    print(f"  {rps:.1f} запросов/сек")
    print(f"  {per_hour:.0f} запросов/час (по ТЗ: ≥1000)")

    if per_hour >= 1000:
        print(f"  ✅ Соответствует ТЗ")
    else:
        print(f"  ⚠️ Ниже требования ТЗ")

    # Вердикт
    print(f"\n{'='*50}")
    all_ok = len(failed) == 0 and degradation <= MAX_DEGRADATION_PERCENT
    if all_ok:
        print("✅ ТЕСТ ПРОЙДЕН — сервис держит нагрузку по ТЗ")
    else:
        print("⚠️ ТЕСТ НЕ ПРОЙДЕН — есть проблемы")
    print(f"{'='*50}")


async def run_mock_test():
    """Нагрузочный тест с моком (без реального сервера)."""
    import tempfile
    import shutil
    from httpx import AsyncClient, ASGITransport

    # Временная папка для результатов теста
    tmp_dir = tempfile.mkdtemp(prefix="load_test_")

    # Мокаем пайплайн и RESULTS_BASE
    from tests.mocks.mock_pipeline import mock_run_pipeline
    import src.api as api_module
    original_pipeline = api_module.run_pipeline
    original_results = api_module.RESULTS_BASE
    api_module.run_pipeline = mock_run_pipeline
    api_module.RESULTS_BASE = tmp_dir

    from src.api import app

    print(f"=== Нагрузочный тест (мок): {CONCURRENT_USERS} одновременных запросов ===")
    print()

    # Базовый замер
    print("Шаг 1: Базовый замер (1 запрос)...")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        image_data = make_fake_image()
        start = time.perf_counter()
        r = await client.post(
            "/generate",
            files={"image": ("plan.jpg", BytesIO(image_data), "image/jpeg")},
            data={"answers": TEST_ANSWERS},
            headers={"X-API-Key": API_KEY},
        )
        baseline_time = time.perf_counter() - start

    print(f"✅ Базовое время: {baseline_time:.3f} сек (status: {r.status_code})")
    print()

    # 50 одновременных
    print(f"Шаг 2: {CONCURRENT_USERS} одновременных запросов...")
    start_total = time.perf_counter()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async def mock_request(i):
            img = make_fake_image()
            s = time.perf_counter()
            resp = await client.post(
                "/generate",
                files={"image": (f"plan_{i}.jpg", BytesIO(img), "image/jpeg")},
                data={"answers": TEST_ANSWERS},
                headers={"X-API-Key": API_KEY},
            )
            return {"user_id": i, "status_code": resp.status_code, "elapsed": time.perf_counter() - s}

        results = await asyncio.gather(*[mock_request(i) for i in range(CONCURRENT_USERS)])

    total_time = time.perf_counter() - start_total

    # Анализ
    success = [r for r in results if r["status_code"] == 200]
    failed = [r for r in results if r["status_code"] != 200]
    times = [r["elapsed"] for r in success]
    avg_time = statistics.mean(times) if times else 0

    degradation = ((avg_time - baseline_time) / baseline_time) * 100 if baseline_time > 0 else 0

    print(f"\n=== РЕЗУЛЬТАТЫ (мок) ===")
    print(f"✅ Успешных: {len(success)}/{len(results)}")
    print(f"Среднее время: {avg_time:.3f} сек")
    print(f"Деградация: {degradation:.1f}% (норма ≤{MAX_DEGRADATION_PERCENT}%)")
    print(f"Общее: {total_time:.3f} сек")
    print(f"RPS: {len(success)/total_time:.0f} | В час: {len(success)/total_time*3600:.0f}")

    # Восстанавливаем
    api_module.run_pipeline = original_pipeline
    api_module.RESULTS_BASE = original_results

    # Удаляем временную папку со всеми результатами теста
    shutil.rmtree(tmp_dir, ignore_errors=True)
    print(f"\n🧹 Временная папка удалена: {tmp_dir}")


if __name__ == "__main__":
    if "--mock" in sys.argv:
        asyncio.run(run_mock_test())
    else:
        asyncio.run(run_load_test())
