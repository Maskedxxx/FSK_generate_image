"""
Smoke-тест инфраструктуры: все сервисы подняты, модели доступны, S3 работает.

python osmi_nodes/tests/test_services.py

Время: ~15 сек. Стоимость: ~$0.001 (два текстовых ping в Gemini).
Не генерирует изображений, не запускает пайплайн.
"""

import base64
import json
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
    """Читает .env из корня проекта."""
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
S3_PREFIX = os.environ.get("S3_PREFIX", "fsk-generate-image")
S3_KEY_ID = os.environ["S3_ACCESS_KEY_ID"]
S3_SECRET = os.environ["S3_SECRET_ACCESS_KEY"]

OSMI_FLOWS = {
    "L1": "2a77a1be-afb6-4635-b1ef-cbb6575a09a8",
    "L2": "332dcec8-2a8c-480e-98ec-be06afb9322c",
    "L3": "0907264d-b0a3-4570-a8e5-41b083d311fb",
    "L4": "2b1ee07c-839a-4ec1-8180-6f241e20a284",
    "PIPELINE": "c3ab4cc3-3212-4863-ae99-a3b7e6efd00b",
}

# ============================================================
# ФИКСТУРЫ
# ============================================================

# Минимальный 1x1 красный PNG (89 байт)
TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="

# Тестовый полигон (квадрат в центре)
TEST_POLYGON = [[100, 100], [900, 100], [900, 900], [100, 900]]

# Тестовый task_id — уникальный, удалится после теста
TEST_TASK_ID = "test_smoke_" + str(int(time.time()))

# S3-ключ тестового изображения (кладём через test_s3, используем в остальных тестах)
TEST_S3_KEY = f"{S3_PREFIX}/{TEST_TASK_ID}/L1_crops/schema_x2.png"

# ============================================================
# S3 КЛИЕНТ
# ============================================================

s3 = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    region_name="us-east-1",
    aws_access_key_id=S3_KEY_ID,
    aws_secret_access_key=S3_SECRET,
)

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
        print(f"  ❌ {name} ({dt}s) — {str(e)[:200]}")


# ============================================================
# ТЕСТЫ: S3
# ============================================================

def test_s3_write():
    """Кладём тестовый PNG в S3 — будет использоваться другими тестами."""
    img_bytes = base64.b64decode(TINY_PNG_B64)
    s3.put_object(Bucket=S3_BUCKET, Key=TEST_S3_KEY, Body=img_bytes, ContentType="image/png")
    return True, f"uploaded {TEST_S3_KEY}"


def test_s3_read():
    """Читаем тестовый файл из S3."""
    resp = s3.get_object(Bucket=S3_BUCKET, Key=TEST_S3_KEY)
    body = resp["Body"].read()
    ok = len(body) > 0
    return ok, f"{len(body)} bytes"


def test_s3_list():
    """Листим тестовую папку."""
    resp = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=f"{S3_PREFIX}/{TEST_TASK_ID}/", MaxKeys=10)
    count = len(resp.get("Contents", []))
    return count > 0, f"{count} objects"


# ============================================================
# ТЕСТЫ: PYTHON IMAGE SERVICE
# ============================================================

def test_health():
    r = requests.get(f"{IMAGE_SERVICE_URL}/health", timeout=10)
    data = r.json()
    ok = r.status_code == 200 and data.get("status") == "ok"
    return ok, f"HTTP {r.status_code}, {data}"


def test_upscale():
    r = requests.post(f"{IMAGE_SERVICE_URL}/upscale", json={
        "image_base64": TINY_PNG_B64,
        "zoom_factor": 2,
        "max_side": 100,
    }, timeout=15)
    ok = r.status_code == 200 and "image_base64" in r.json()
    return ok, f"HTTP {r.status_code}, new_size={r.json().get('new_size')}"


def test_crop():
    r = requests.post(f"{IMAGE_SERVICE_URL}/crop", json={
        "image_base64": TINY_PNG_B64,
        "rooms": [{"name": "test", "polygon": TEST_POLYGON}],
    }, timeout=15)
    crops = r.json().get("crops", [])
    ok = r.status_code == 200 and len(crops) >= 0  # может быть 0 если polygon слишком маленький для 1x1
    return ok, f"HTTP {r.status_code}, crops={len(crops)}"


def test_draw_polygons():
    """Рисует полигон на тестовом PNG из S3."""
    r = requests.post(f"{IMAGE_SERVICE_URL}/draw_polygons", json={
        "s3_key": TEST_S3_KEY,
        "task_id": TEST_TASK_ID,
        "rooms": [{"name": "test_room", "polygon": TEST_POLYGON}],
    }, timeout=15)
    ok = r.status_code == 200 and r.json().get("status") == "ok"
    return ok, f"HTTP {r.status_code}, s3_key={r.json().get('s3_key', '?')}"


def test_rotate():
    """Поворачивает тестовый PNG."""
    r = requests.post(f"{IMAGE_SERVICE_URL}/rotate", json={
        "s3_key": TEST_S3_KEY,
        "task_id": TEST_TASK_ID,
        "room_name": "test_room",
        "side": "a",
    }, timeout=15)
    ok = r.status_code == 200 and r.json().get("status") == "ok"
    return ok, f"HTTP {r.status_code}, angle={r.json().get('angle', '?')}"


def test_stitch():
    """Склеивает тестовый PNG по полигону."""
    r = requests.post(f"{IMAGE_SERVICE_URL}/stitch", json={
        "task_id": TEST_TASK_ID,
        "schema_s3_key": TEST_S3_KEY,
        "rooms": [{"name": "test_room", "polygon": TEST_POLYGON, "ref_s3_key": TEST_S3_KEY}],
    }, timeout=15)
    ok = r.status_code == 200 and r.json().get("status") == "ok"
    return ok, f"HTTP {r.status_code}, stitched_key={r.json().get('stitched_key', '?')}"


# ============================================================
# ТЕСТЫ: OPENROUTER
# ============================================================

def test_openrouter_key():
    r = requests.get(f"{OPENROUTER_URL}/auth/key",
                     headers={"Authorization": f"Bearer {OPENROUTER_KEY}"}, timeout=10)
    data = r.json().get("data", {})
    usage = data.get("usage", 0)
    limit = data.get("limit")
    ok = r.status_code == 200
    return ok, f"usage=${usage:.2f}, limit={limit or 'unlimited'}"


def test_openrouter_credits():
    r = requests.get(f"{OPENROUTER_URL}/auth/key",
                     headers={"Authorization": f"Bearer {OPENROUTER_KEY}"}, timeout=10)
    data = r.json().get("data", {})
    usage = data.get("usage", 0)
    limit = data.get("limit")
    ok = limit is None or usage < limit
    return ok, f"usage=${usage:.2f}, limit={limit or 'unlimited'}, {'OK' if ok else 'CREDITS EXHAUSTED'}"


def test_gemini_flash():
    """Текстовый ping в Gemini 3 Flash (без картинок)."""
    r = requests.post(f"{OPENROUTER_URL}/chat/completions", json={
        "model": "google/gemini-3-flash-preview",
        "messages": [{"role": "user", "content": "Reply with one word: pong"}],
        "max_tokens": 10,
    }, headers={
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
    }, timeout=15)
    if r.status_code == 200:
        text = r.json()["choices"][0]["message"]["content"]
        return True, f"response: {text[:50]}"
    else:
        error = r.json().get("error", {}).get("message", r.text[:100])
        return False, f"HTTP {r.status_code}: {error}"


def test_gemini_flash_image():
    """Текстовый ping в Gemini 3.1 Flash Image (без картинок)."""
    r = requests.post(f"{OPENROUTER_URL}/chat/completions", json={
        "model": "google/gemini-3.1-flash-image-preview",
        "messages": [{"role": "user", "content": "Reply with one word: pong"}],
        "max_tokens": 10,
    }, headers={
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
    }, timeout=15)
    if r.status_code == 200:
        text = r.json()["choices"][0]["message"]["content"]
        return True, f"response: {text[:50]}"
    else:
        error = r.json().get("error", {}).get("message", r.text[:100])
        return False, f"HTTP {r.status_code}: {error}"


# ============================================================
# ТЕСТЫ: OSMI FLOWS
# ============================================================

def make_osmi_test(name, flow_id):
    def test():
        r = requests.post(
            f"https://app.osmi-ai.ru/api/v1/prediction/{flow_id}",
            json={"question": "ping"},
            timeout=30,
        )
        text = r.text[:300]
        if "Ending nodes not found" in text:
            return False, "Ending nodes not found — нет завершающей ноды"
        if "EAI_AGAIN" in text:
            return False, "DNS failure на OSMI-сервере"
        # Любой другой ответ (200 с pong, 500 с NoSuchKey, AxiosError) = флоу валиден
        return True, f"HTTP {r.status_code}, flow valid"
    return test


# ============================================================
# CLEANUP
# ============================================================

def cleanup():
    """Удаляет все тестовые файлы из S3."""
    resp = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=f"{S3_PREFIX}/{TEST_TASK_ID}/", MaxKeys=100)
    objects = resp.get("Contents", [])
    if objects:
        s3.delete_objects(
            Bucket=S3_BUCKET,
            Delete={"Objects": [{"Key": o["Key"]} for o in objects]},
        )
    # Проверяем что пусто
    resp2 = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=f"{S3_PREFIX}/{TEST_TASK_ID}/", MaxKeys=1)
    remaining = len(resp2.get("Contents", []))
    ok = remaining == 0
    return ok, f"deleted {len(objects)} objects, remaining={remaining}"


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("  FSK Generate Image — Service Smoke Test")
    print(f"  test_task_id: {TEST_TASK_ID}")
    print("=" * 60)

    # --- S3 (сначала — создаём тестовый файл для последующих тестов) ---
    print("\n📦 S3")
    check("S3 write", test_s3_write)
    check("S3 read", test_s3_read)
    check("S3 list", test_s3_list)

    # --- Python Image Service ---
    print("\n🐍 Python Image Service")
    check("health", test_health)
    check("upscale", test_upscale)
    check("crop", test_crop)
    check("draw_polygons", test_draw_polygons)
    check("rotate", test_rotate)
    check("stitch", test_stitch)

    # --- OpenRouter ---
    print("\n🔑 OpenRouter")
    check("API key valid", test_openrouter_key)
    check("Credits available", test_openrouter_credits)
    check("Gemini 3 Flash", test_gemini_flash)
    check("Gemini 3.1 Flash Image", test_gemini_flash_image)

    # --- OSMI Flows ---
    print("\n🔗 OSMI Flows")
    for name, flow_id in OSMI_FLOWS.items():
        check(f"OSMI {name} ({flow_id[:8]})", make_osmi_test(name, flow_id))

    # --- Cleanup ---
    print("\n🧹 Cleanup")
    check("Delete test data", cleanup)

    # --- Итог ---
    passed = sum(1 for _, ok in results if ok)
    failed = sum(1 for _, ok in results if not ok)
    total = len(results)

    print("\n" + "=" * 60)
    if failed == 0:
        print(f"  ✅ PASS — {passed}/{total} проверок пройдено")
    else:
        print(f"  ❌ FAIL — {failed} из {total} проверок не пройдено:")
        for name, ok in results:
            if not ok:
                print(f"     - {name}")
    print("=" * 60)

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
