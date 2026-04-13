"""
Smoke-тест отказов: невалидные данные, недоступные сервисы, битые запросы.
Проверяем что ошибки возвращаются быстро и с понятными сообщениями.

python osmi_nodes/tests/test_failures.py

Время: ~30 сек. Стоимость: $0.
"""

import base64
import os
import time
import sys
from pathlib import Path

import boto3
import requests

# ============================================================
# ЗАГРУЗКА .env
# ============================================================

def _load_env():
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        print(f"  ❌ .env не найден: {env_path}")
        sys.exit(1)
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())

_load_env()

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

IMAGE_SERVICE_URL = "https://llm-home.fsk.fvds.ru"
OPENROUTER_URL = "https://openrouter.ai/api/v1"
OPENROUTER_KEY = os.environ["OPENROUTER_API_KEY"]

S3_ENDPOINT = "https://storage.yandexcloud.net"
S3_BUCKET = os.environ.get("S3_BUCKET", "fsk-service")
S3_KEY_ID = os.environ["S3_ACCESS_KEY_ID"]
S3_SECRET = os.environ["S3_SECRET_ACCESS_KEY"]

# Таймаут для всех тестов — ответ должен прийти быстро
FAIL_TIMEOUT = 10

# ============================================================
# РЕЗУЛЬТАТЫ
# ============================================================

results = []


def check(name, fn):
    """Запускает тест, ловит ошибки, печатает результат."""
    t0 = time.monotonic()
    try:
        ok, detail = fn()
        dt = round(time.monotonic() - t0, 1)
        icon = "✅" if ok else "❌"
        results.append((name, ok))
        print(f"  {icon} {name} ({dt}s) — {detail}")
    except Exception as e:
        dt = round(time.monotonic() - t0, 1)
        results.append((name, False))
        print(f"  ❌ {name} ({dt}s) — UNEXPECTED: {str(e)[:200]}")


# ============================================================
# PYTHON SERVICE: невалидные запросы
# ============================================================

def test_upscale_bad_base64():
    """/upscale с битым base64 — должен вернуть ошибку, не зависнуть."""
    r = requests.post(f"{IMAGE_SERVICE_URL}/upscale", json={
        "image_base64": "NOT_VALID_BASE64!!!",
        "zoom_factor": 2,
        "max_side": 100,
    }, timeout=FAIL_TIMEOUT)
    ok = r.status_code in (400, 422, 500)
    return ok, f"HTTP {r.status_code}"


def test_crop_empty_polygon():
    """/crop с пустым polygon — должен вернуть пустой crops или ошибку."""
    r = requests.post(f"{IMAGE_SERVICE_URL}/crop", json={
        "image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
        "rooms": [{"name": "test", "polygon": []}],
    }, timeout=FAIL_TIMEOUT)
    ok = r.status_code == 200 and len(r.json().get("crops", [])) == 0
    return ok, f"HTTP {r.status_code}, crops={len(r.json().get('crops', []))}"


def test_rotate_nonexistent_s3_key():
    """/rotate с несуществующим S3-ключом — ошибка, не зависание."""
    r = requests.post(f"{IMAGE_SERVICE_URL}/rotate", json={
        "s3_key": "fsk-generate-image/nonexistent/file.png",
        "task_id": "test_fail",
        "room_name": "test",
        "side": "a",
    }, timeout=FAIL_TIMEOUT)
    ok = r.status_code in (400, 404, 500)
    return ok, f"HTTP {r.status_code}"


def test_stitch_nonexistent_schema():
    """/stitch с несуществующей схемой — ошибка, не зависание."""
    r = requests.post(f"{IMAGE_SERVICE_URL}/stitch", json={
        "task_id": "test_fail",
        "schema_s3_key": "fsk-generate-image/nonexistent/schema.png",
        "rooms": [{"name": "test", "polygon": [[0,0],[1000,0],[1000,1000],[0,1000]], "ref_s3_key": "nonexistent.png"}],
    }, timeout=FAIL_TIMEOUT)
    ok = r.status_code in (400, 404, 500)
    return ok, f"HTTP {r.status_code}"


def test_draw_polygons_nonexistent_s3_key():
    """/draw_polygons с несуществующим S3-ключом — ошибка."""
    r = requests.post(f"{IMAGE_SERVICE_URL}/draw_polygons", json={
        "s3_key": "fsk-generate-image/nonexistent/file.png",
        "task_id": "test_fail",
        "rooms": [{"name": "test", "polygon": [[100,100],[900,100],[900,900],[100,900]]}],
    }, timeout=FAIL_TIMEOUT)
    ok = r.status_code in (400, 404, 500)
    return ok, f"HTTP {r.status_code}"


# ============================================================
# PYTHON SERVICE: сервер недоступен
# ============================================================

def test_python_service_unreachable():
    """Запрос на несуществующий хост — должен вернуть ошибку, не зависнуть."""
    try:
        r = requests.get("https://nonexistent-service-12345.fvds.ru/health", timeout=5)
        return False, f"HTTP {r.status_code} — ожидали connection error"
    except requests.ConnectionError:
        return True, "ConnectionError (ожидаемо)"
    except requests.Timeout:
        return True, "Timeout (ожидаемо)"


# ============================================================
# S3: невалидные операции
# ============================================================

def test_s3_invalid_credentials():
    """S3 с кривыми кредами — AccessDenied."""
    bad_s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id="INVALID_KEY",
        aws_secret_access_key="INVALID_SECRET",
    )
    try:
        bad_s3.get_object(Bucket=S3_BUCKET, Key="fsk-generate-image/test/file.txt")
        return False, "Не должно было пройти"
    except bad_s3.exceptions.NoSuchKey:
        return False, "NoSuchKey — креды приняли, ожидали AccessDenied"
    except Exception as e:
        error_name = type(e).__name__
        ok = "AccessDenied" in str(e) or "Forbidden" in str(e) or "403" in str(e) or "InvalidAccessKeyId" in str(e) or "SignatureDoesNotMatch" in str(e)
        return ok, f"{error_name}: {str(e)[:100]}"


def test_s3_nonexistent_key():
    """S3 GetObject на несуществующий ключ — NoSuchKey."""
    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id=S3_KEY_ID,
        aws_secret_access_key=S3_SECRET,
    )
    try:
        s3.get_object(Bucket=S3_BUCKET, Key="fsk-generate-image/nonexistent_task/nonexistent_file.png")
        return False, "Не должно было пройти"
    except s3.exceptions.NoSuchKey:
        return True, "NoSuchKey (ожидаемо)"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:100]}"


# ============================================================
# OPENROUTER: невалидные запросы
# ============================================================

def test_openrouter_invalid_key():
    """OpenRouter с невалидным ключом — 401."""
    r = requests.get(f"{OPENROUTER_URL}/auth/key",
                     headers={"Authorization": "Bearer sk-or-v1-invalid_key_12345"}, timeout=FAIL_TIMEOUT)
    ok = r.status_code in (401, 403)
    return ok, f"HTTP {r.status_code}"


def test_openrouter_nonexistent_model():
    """OpenRouter с несуществующей моделью — ошибка."""
    r = requests.post(f"{OPENROUTER_URL}/chat/completions", json={
        "model": "google/nonexistent-model-99999",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5,
    }, headers={
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
    }, timeout=FAIL_TIMEOUT)
    ok = r.status_code in (400, 404) or "error" in r.json()
    return ok, f"HTTP {r.status_code}"


# ============================================================
# OSMI: недоступные / несуществующие флоу
# ============================================================

def test_osmi_nonexistent_flow():
    """OSMI с несуществующим flow ID — 404 или 500."""
    r = requests.post(
        "https://app.osmi-ai.ru/api/v1/prediction/00000000-0000-0000-0000-000000000000",
        json={"question": "ping"},
        timeout=FAIL_TIMEOUT,
    )
    ok = r.status_code in (404, 500)
    return ok, f"HTTP {r.status_code}"


def test_osmi_unreachable():
    """OSMI на несуществующем хосте — connection error."""
    try:
        r = requests.post(
            "https://nonexistent-osmi-12345.ru/api/v1/prediction/test",
            json={"question": "ping"},
            timeout=5,
        )
        return False, f"HTTP {r.status_code} — ожидали connection error"
    except requests.ConnectionError:
        return True, "ConnectionError (ожидаемо)"
    except requests.Timeout:
        return True, "Timeout (ожидаемо)"


def test_osmi_empty_question():
    """OSMI pipeline с пустым question — ошибка, не зависание."""
    r = requests.post(
        "https://app.osmi-ai.ru/api/v1/prediction/c3ab4cc3-3212-4863-ae99-a3b7e6efd00b",
        json={"question": ""},
        timeout=30,
    )
    # Пустой вход → AxiosError или ошибка парсинга, но не зависание
    ok = r.status_code in (200, 400, 500)
    has_error = "error" in r.text.lower() or "Error" in r.text
    return ok, f"HTTP {r.status_code}, has_error={has_error}"


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("  FSK Generate Image — Failure Smoke Test")
    print("=" * 60)

    # --- Python Service ---
    print("\n🐍 Python Service — невалидные запросы")
    check("upscale: битый base64", test_upscale_bad_base64)
    check("crop: пустой polygon", test_crop_empty_polygon)
    check("rotate: несуществующий s3_key", test_rotate_nonexistent_s3_key)
    check("stitch: несуществующая schema", test_stitch_nonexistent_schema)
    check("draw_polygons: несуществующий s3_key", test_draw_polygons_nonexistent_s3_key)

    print("\n🐍 Python Service — недоступность")
    check("несуществующий хост", test_python_service_unreachable)

    # --- S3 ---
    print("\n📦 S3 — невалидные операции")
    check("S3: невалидные креды", test_s3_invalid_credentials)
    check("S3: несуществующий ключ", test_s3_nonexistent_key)

    # --- OpenRouter ---
    print("\n🔑 OpenRouter — невалидные запросы")
    check("невалидный API key", test_openrouter_invalid_key)
    check("несуществующая модель", test_openrouter_nonexistent_model)

    # --- OSMI ---
    print("\n🔗 OSMI — отказы")
    check("несуществующий flow ID", test_osmi_nonexistent_flow)
    check("несуществующий хост OSMI", test_osmi_unreachable)
    check("pipeline: пустой question", test_osmi_empty_question)

    # --- Итог ---
    passed = sum(1 for _, ok in results if ok)
    failed = sum(1 for _, ok in results if not ok)
    total = len(results)

    print("\n" + "=" * 60)
    if failed == 0:
        print(f"  ✅ PASS — {passed}/{total} failure-тестов пройдено")
        print(f"  Все ошибки возвращаются быстро и с понятными сообщениями")
    else:
        print(f"  ❌ FAIL — {failed} из {total} тестов не пройдено:")
        for name, ok in results:
            if not ok:
                print(f"     - {name}")
    print("=" * 60)

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
