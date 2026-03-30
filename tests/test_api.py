"""
Тесты API эндпоинтов — TDD.

Тестирует POST /generate с разными сценариями по ТЗ:
    - Валидные форматы: JPG, JPEG, PNG, SVG, HEIF, HEIC
    - Невалидные форматы: PDF, GIF, BMP и т.д.
    - Размер файла: до 20 МБ (ок), больше 20 МБ (ошибка)
    - Опросник: все вопросы обязательны, варианты валидируются
    - Лимит: 3 генерации на сессию
    - Статус и результат: GET /status, GET /result

Запуск: pytest tests/test_api.py -v
"""

import sys
import os
import json
import pytest
from io import BytesIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from httpx import AsyncClient, ASGITransport
from src.api import app, tasks
from src.questionnaire import TEST_ANSWERS
from tests.mocks.mock_pipeline import mock_run_pipeline, mock_run_pipeline_slow


# === ФИКСТУРЫ ===


from src.config import FSK_API_KEY
API_KEY_HEADER = {"X-API-Key": FSK_API_KEY}


@pytest.fixture(autouse=True)
def mock_pipeline(monkeypatch):
    """Подменяет run_pipeline на мок — не вызывает реальный API."""
    monkeypatch.setattr("src.api.run_pipeline", mock_run_pipeline)


@pytest.fixture(autouse=True)
def clear_tasks(tmp_path, monkeypatch):
    """Перенаправляет результаты и лимиты во временную папку."""
    import shutil
    tasks.clear()
    # Все результаты и лимиты пишутся во временную папку
    monkeypatch.setattr("src.api.RESULTS_BASE", str(tmp_path))
    yield
    tasks.clear()


# Оставляем старую очистку на случай мусора от прошлых прогонов
@pytest.fixture(autouse=True)
def _legacy_cleanup():
    """Чистит мусор от старых прогонов."""
    import shutil
    sessions_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results", "sessions")
    if os.path.exists(sessions_dir):
        for d in os.listdir(sessions_dir):
            if d.startswith("test-"):
                shutil.rmtree(os.path.join(sessions_dir, d), ignore_errors=True)
    yield


def _make_image(size_kb: int = 10, ext: str = "jpg") -> tuple[BytesIO, str]:
    """
    Создаёт фейковое изображение заданного размера.

    Принимает:
        size_kb — размер в килобайтах
        ext — расширение файла

    Возвращает:
        (BytesIO с данными, имя файла)
    """
    data = b"\x00" * (size_kb * 1024)
    return BytesIO(data), f"test_plan.{ext}"


def _valid_answers() -> str:
    """Возвращает валидный JSON опросника."""
    return json.dumps(TEST_ANSWERS)


# === ТЕСТЫ: ПРОВЕРКА РАБОТОСПОСОБНОСТИ ===


@pytest.mark.anyio
async def test_root():
    """GET / — сервис отвечает."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.get("/")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.anyio
async def test_no_api_key():
    """POST /generate без API-ключа — 401."""
    img, name = _make_image()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/generate", files={"image": (name, img, "image/jpeg")}, data={"answers": _valid_answers()})
    assert r.status_code == 401


@pytest.mark.anyio
async def test_wrong_api_key():
    """POST /generate с неверным ключом — 401."""
    img, name = _make_image()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"X-API-Key": "wrong-key"}) as client:
        r = await client.post("/generate", files={"image": (name, img, "image/jpeg")}, data={"answers": _valid_answers()})
    assert r.status_code == 401


@pytest.mark.anyio
async def test_questionnaire():
    """GET /questionnaire — возвращает структуру опросника."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.get("/questionnaire")
    assert r.status_code == 200
    data = r.json()
    # Все 9 вопросов на месте
    assert "style" in data
    assert "colors" in data
    assert "materials" in data
    assert "residents" in data
    assert "work_from_home" in data
    assert "hobby" in data
    assert "bathroom_layout" in data
    assert "bath_type" in data
    assert "storage" in data


# === ТЕСТЫ: ВАЛИДНЫЕ ФОРМАТЫ ФАЙЛОВ ===


@pytest.mark.anyio
async def test_generate_jpg():
    """POST /generate с JPG — принимает."""
    img, name = _make_image(ext="jpg")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.post("/generate", files={"image": (name, img, "image/jpeg")}, data={"answers": _valid_answers()})
    assert r.status_code == 200
    assert "task_id" in r.json()


@pytest.mark.anyio
async def test_generate_png():
    """POST /generate с PNG — принимает."""
    img, name = _make_image(ext="png")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.post("/generate", files={"image": (name, img, "image/png")}, data={"answers": _valid_answers()})
    assert r.status_code == 200
    assert "task_id" in r.json()


@pytest.mark.anyio
async def test_generate_jpeg():
    """POST /generate с JPEG — принимает."""
    img, name = _make_image(ext="jpeg")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.post("/generate", files={"image": (name, img, "image/jpeg")}, data={"answers": _valid_answers()})
    assert r.status_code == 200
    assert "task_id" in r.json()


@pytest.mark.anyio
async def test_generate_svg():
    """POST /generate с SVG — принимает (по ТЗ)."""
    img, name = _make_image(ext="svg")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.post("/generate", files={"image": (name, img, "image/svg+xml")}, data={"answers": _valid_answers()})
    assert r.status_code == 200
    assert "task_id" in r.json()


@pytest.mark.anyio
async def test_generate_heif():
    """POST /generate с HEIF — принимает (по ТЗ)."""
    img, name = _make_image(ext="heif")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.post("/generate", files={"image": (name, img, "image/heif")}, data={"answers": _valid_answers()})
    assert r.status_code == 200
    assert "task_id" in r.json()


@pytest.mark.anyio
async def test_generate_heic():
    """POST /generate с HEIC — принимает (по ТЗ)."""
    img, name = _make_image(ext="heic")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.post("/generate", files={"image": (name, img, "image/heic")}, data={"answers": _valid_answers()})
    assert r.status_code == 200
    assert "task_id" in r.json()


# === ТЕСТЫ: НЕВАЛИДНЫЕ ФОРМАТЫ ===


@pytest.mark.anyio
async def test_reject_pdf():
    """POST /generate с PDF — отклоняет."""
    img, name = _make_image(ext="pdf")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.post("/generate", files={"image": (name, img, "application/pdf")}, data={"answers": _valid_answers()})
    assert r.status_code == 400
    assert "формат" in r.json()["error"].lower() or "format" in r.json()["error"].lower()


@pytest.mark.anyio
async def test_reject_gif():
    """POST /generate с GIF — отклоняет."""
    img, name = _make_image(ext="gif")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.post("/generate", files={"image": (name, img, "image/gif")}, data={"answers": _valid_answers()})
    assert r.status_code == 400


@pytest.mark.anyio
async def test_reject_bmp():
    """POST /generate с BMP — отклоняет."""
    img, name = _make_image(ext="bmp")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.post("/generate", files={"image": (name, img, "image/bmp")}, data={"answers": _valid_answers()})
    assert r.status_code == 400


@pytest.mark.anyio
async def test_no_image():
    """POST /generate без файла — 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.post("/generate", data={"answers": _valid_answers()})
    assert r.status_code == 422


@pytest.mark.anyio
async def test_no_answers():
    """POST /generate без опросника — 422."""
    img, name = _make_image()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.post("/generate", files={"image": (name, img, "image/jpeg")})
    assert r.status_code == 422


@pytest.mark.anyio
async def test_empty_file():
    """POST /generate с пустым файлом (0 байт) — 400."""
    img = BytesIO(b"")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.post("/generate", files={"image": ("empty.jpg", img, "image/jpeg")}, data={"answers": _valid_answers()})
    assert r.status_code == 400


# === ТЕСТЫ: РАЗМЕР ФАЙЛА ===


@pytest.mark.anyio
async def test_reject_oversize_file():
    """POST /generate с файлом > 20 МБ — отклоняет."""
    img, name = _make_image(size_kb=21 * 1024, ext="jpg")  # 21 МБ
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.post("/generate", files={"image": (name, img, "image/jpeg")}, data={"answers": _valid_answers()})
    assert r.status_code == 400
    assert "20" in r.json()["error"]


@pytest.mark.anyio
async def test_accept_max_size_file():
    """POST /generate с файлом ровно 20 МБ — принимает."""
    img, name = _make_image(size_kb=20 * 1024, ext="jpg")  # 20 МБ
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.post("/generate", files={"image": (name, img, "image/jpeg")}, data={"answers": _valid_answers()})
    assert r.status_code == 200


# === ТЕСТЫ: ВАЛИДАЦИЯ ОПРОСНИКА ===


@pytest.mark.anyio
async def test_reject_invalid_json():
    """POST /generate с невалидным JSON — отклоняет."""
    img, name = _make_image()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.post("/generate", files={"image": (name, img, "image/jpeg")}, data={"answers": "not json{{"})
    assert r.status_code == 400
    assert "JSON" in r.json()["error"]


@pytest.mark.anyio
async def test_reject_missing_question():
    """POST /generate с неполным опросником — отклоняет."""
    incomplete = {"style": "Скандинавский"}  # только 1 из 9
    img, name = _make_image()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.post("/generate", files={"image": (name, img, "image/jpeg")}, data={"answers": json.dumps(incomplete)})
    assert r.status_code == 400
    assert "Отсутствует" in r.json()["error"]


@pytest.mark.anyio
async def test_reject_invalid_answer():
    """POST /generate с недопустимым вариантом ответа — отклоняет."""
    bad_answers = {**TEST_ANSWERS, "style": "Несуществующий стиль"}
    img, name = _make_image()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.post("/generate", files={"image": (name, img, "image/jpeg")}, data={"answers": json.dumps(bad_answers)})
    assert r.status_code == 400
    assert "Недопустимый" in r.json()["error"]


# === ТЕСТЫ: TASK_ID ===


@pytest.mark.anyio
async def test_generate_returns_task_id():
    """POST /generate — возвращает task_id."""
    img, name = _make_image()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.post("/generate", files={"image": (name, img, "image/jpeg")}, data={"answers": _valid_answers()})
    assert r.status_code == 200
    assert "task_id" in r.json()
    assert len(r.json()["task_id"]) == 8


# === ТЕСТЫ: СТАТУС И РЕЗУЛЬТАТ ===


@pytest.mark.anyio
async def test_status_valid_task():
    """GET /status/{task_id} — возвращает статус."""
    img, name = _make_image()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        # Создаём задачу
        r = await client.post("/generate", files={"image": (name, img, "image/jpeg")}, data={"answers": _valid_answers()})
        task_id = r.json()["task_id"]

        # Проверяем статус
        r = await client.get(f"/status/{task_id}")
    assert r.status_code == 200
    assert r.json()["status"] in ["processing", "done", "error"]


@pytest.mark.anyio
async def test_status_unknown_task():
    """GET /status/{bad_id} — 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.get("/status/nonexistent-id")
    assert r.status_code == 404


@pytest.mark.anyio
async def test_result_unknown_task():
    """GET /result/{bad_id} — 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.get("/result/nonexistent-id")
    assert r.status_code == 404


@pytest.mark.anyio
async def test_result_done():
    """GET /result/{task_id} после завершения — 200 с результатом."""
    import time
    img, name = _make_image()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=API_KEY_HEADER) as client:
        r = await client.post("/generate", files={"image": (name, img, "image/jpeg")}, data={"answers": _valid_answers()})
        task_id = r.json()["task_id"]

        # Ждём завершения фоновой задачи (мок быстрый)
        time.sleep(0.5)

        r = await client.get(f"/result/{task_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "done"
    assert r.json()["result"]["rooms_count"] == 2
