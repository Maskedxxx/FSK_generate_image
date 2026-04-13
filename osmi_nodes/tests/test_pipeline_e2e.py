"""
E2E smoke-тест пайплайна: реальные вызовы Python-сервиса + S3, моки вместо Gemini.

Проверяет что вся инфраструктура работает и S3-структура создаётся правильно.
Не генерирует изображений через Gemini — экономит кредиты и время.

python osmi_nodes/tests/test_pipeline_e2e.py              # полный прогон + cleanup
python osmi_nodes/tests/test_pipeline_e2e.py --no-cleanup # оставить артефакты
python osmi_nodes/tests/test_pipeline_e2e.py --task-id X  # валидация существующей задачи

Время: ~20 сек. Стоимость: $0.
"""

import argparse
import base64
import json
import os
import sys
import time
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

S3_ENDPOINT = "https://storage.yandexcloud.net"
S3_BUCKET = os.environ.get("S3_BUCKET", "fsk-service")
S3_PREFIX = os.environ.get("S3_PREFIX", "fsk-generate-image")
S3_KEY_ID = os.environ["S3_ACCESS_KEY_ID"]
S3_SECRET = os.environ["S3_SECRET_ACCESS_KEY"]

# Пути к фикстурам
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
TEST_PLAN_PATH = os.path.join(FIXTURES_DIR, "test_plan.jpg")
TEST_ANALYSIS_PATH = os.path.join(FIXTURES_DIR, "test_analysis.json")

# Минимальные размеры файлов (KB)
MIN_SIZE = {
    "schema": 50,
    "polygons": 20,
    "crop": 10,
    "reference": 0.05,  # моки маленькие
    "side": 0.05,       # моки маленькие
    "stitched": 1,
    "composite": 0.05,  # мок маленький
}

# Минимальный PNG для моков (1x1 красный)
TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
TINY_PNG_BYTES = base64.b64decode(TINY_PNG_B64)

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
task_id = None


def check(name, ok, detail=""):
    icon = "✅" if ok else "❌"
    results.append((name, ok))
    print(f"  {icon} {name} — {detail}")
    return ok


def s3_put(key, body, content_type="image/png"):
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=body, ContentType=content_type)


def s3_get_size(key):
    try:
        resp = s3.head_object(Bucket=S3_BUCKET, Key=key)
        return resp["ContentLength"] // 1024
    except Exception:
        return -1


def s3_list(prefix):
    resp = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix, MaxKeys=200)
    return [(o["Key"], o["Size"]) for o in resp.get("Contents", [])]


# ============================================================
# ШАГ 1: СЛОЙ 1 — реальные вызовы Python-сервиса
# ============================================================

def step1_layer1():
    """L1: upscale (реальный) → analysis (мок) → draw_polygons (реальный) → crop (реальный)."""
    global task_id

    print("\n📐 Шаг 1: Слой 1 (upscale + analysis мок + polygons + crop)")

    # 1.1 Читаем план, генерируем task_id
    with open(TEST_PLAN_PATH, "rb") as f:
        plan_b64 = base64.b64encode(f.read()).decode()

    task_id = "test_e2e_" + str(int(time.time()))
    prefix = f"{S3_PREFIX}/{task_id}"

    # 1.2 /upscale — реальный вызов с task_id → сохраняет в S3
    t0 = time.monotonic()
    r = requests.post(f"{IMAGE_SERVICE_URL}/upscale", json={
        "image_base64": plan_b64,
        "task_id": task_id,
        "zoom_factor": 4,
        "max_side": 4000,
    }, timeout=30)
    dt = round(time.monotonic() - t0, 1)
    check("L1 /upscale", r.status_code == 200, f"{dt}s, s3_key={r.json().get('s3_key', '?')}")
    schema_key = r.json().get("s3_key", "")

    # 1.3 meta.json — сохраняем сами (мок ноды 2)
    meta = {"created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"), "type": "pipeline", "answers": {"style": "test"}}
    s3_put(f"{prefix}/meta.json", json.dumps(meta, indent=2), "application/json")
    check("L1 meta.json", True, "saved")

    # 1.4 analysis.json — мок (фикстура вместо Gemini)
    with open(TEST_ANALYSIS_PATH) as f:
        analysis = json.load(f)
    s3_put(f"{prefix}/L1_crops/analysis.json", json.dumps(analysis, indent=2, ensure_ascii=False), "application/json")
    check("L1 analysis.json (мок)", True, f"{len(analysis['rooms'])} rooms")

    # 1.5 L1_meta.json — сохраняем сами
    l1_meta = {"layer": 1, "model": "mock", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")}
    s3_put(f"{prefix}/L1_crops/L1_meta.json", json.dumps(l1_meta, indent=2), "application/json")
    check("L1 L1_meta.json", True, "saved")

    # 1.6 /draw_polygons — реальный вызов
    rooms_for_api = [{"name": r["name"], "polygon": r["polygon"]} for r in analysis["rooms"]]
    t0 = time.monotonic()
    r = requests.post(f"{IMAGE_SERVICE_URL}/draw_polygons", json={
        "s3_key": schema_key,
        "task_id": task_id,
        "rooms": rooms_for_api,
    }, timeout=30)
    dt = round(time.monotonic() - t0, 1)
    check("L1 /draw_polygons", r.status_code == 200, f"{dt}s")

    # 1.7 /crop — реальный вызов, параллельно (как в ноде 5)
    t0 = time.monotonic()
    crops = []
    for i, room in enumerate(analysis["rooms"]):
        cr = requests.post(f"{IMAGE_SERVICE_URL}/crop", json={
            "s3_key": schema_key,
            "rooms": [{"name": room["name"], "polygon": room["polygon"]}],
        }, timeout=30)
        if cr.status_code == 200 and cr.json().get("crops"):
            crop_data = cr.json()["crops"][0]
            safe_name = room["name"].replace(" ", "_").replace("/", "-")
            crop_key = f"{prefix}/L1_crops/{i+1}_{safe_name}_crop.png"
            s3_put(crop_key, base64.b64decode(crop_data["image_base64"]))
            crops.append(crop_key)
    dt = round(time.monotonic() - t0, 1)
    check(f"L1 /crop × {len(analysis['rooms'])}", len(crops) == len(analysis["rooms"]),
          f"{dt}s, {len(crops)} crops saved")

    return analysis


# ============================================================
# ШАГ 2: СЛОЙ 2 — моки вместо Gemini Image
# ============================================================

def step2_layer2(analysis):
    """L2: кладём заглушки-картинки в L2_references/ (мок вместо Gemini)."""
    print("\n🎨 Шаг 2: Слой 2 (моки референсов)")

    prefix = f"{S3_PREFIX}/{task_id}"
    for room in analysis["rooms"]:
        safe_name = room["name"].replace(" ", "_").replace("/", "-")
        key = f"{prefix}/L2_references/{safe_name}.png"
        s3_put(key, TINY_PNG_BYTES)

    refs = s3_list(f"{prefix}/L2_references/")
    check(f"L2 references == {len(analysis['rooms'])}", len(refs) == len(analysis["rooms"]),
          f"{len(refs)} files")


# ============================================================
# ШАГ 3: СЛОЙ 3 — реальный /rotate + моки рендеров
# ============================================================

def step3_layer3(analysis):
    """L3: /rotate реальный (prepared), моки для side_a/side_b."""
    print("\n📷 Шаг 3: Слой 3 (реальный /rotate + моки рендеров)")

    prefix = f"{S3_PREFIX}/{task_id}"

    # /rotate — реальный вызов для каждой комнаты × 2 стороны
    rotate_count = 0
    t0 = time.monotonic()
    for room in analysis["rooms"]:
        safe_name = room["name"].replace(" ", "_").replace("/", "-")
        ref_key = f"{prefix}/L2_references/{safe_name}.png"
        for side in ["a", "b"]:
            r = requests.post(f"{IMAGE_SERVICE_URL}/rotate", json={
                "s3_key": ref_key,
                "task_id": task_id,
                "room_name": room["name"],
                "side": side,
            }, timeout=30)
            if r.status_code == 200:
                rotate_count += 1
    dt = round(time.monotonic() - t0, 1)
    expected = len(analysis["rooms"]) * 2
    check(f"L3 /rotate × {expected}", rotate_count == expected, f"{dt}s, {rotate_count} prepared")

    # side_a / side_b — моки
    mock_count = 0
    for room in analysis["rooms"]:
        safe_name = room["name"].replace(" ", "_").replace("/", "-")
        for side in ["a", "b"]:
            key = f"{prefix}/L3_renders/{safe_name}_side_{side}.png"
            s3_put(key, TINY_PNG_BYTES)
            mock_count += 1
    check(f"L3 side renders (моки) × {expected}", mock_count == expected, f"{mock_count} files")


# ============================================================
# ШАГ 4: СЛОЙ 4 — реальный /stitch + мок composite
# ============================================================

def step4_layer4(analysis):
    """L4: /stitch реальный, composite мок."""
    print("\n🏠 Шаг 4: Слой 4 (реальный /stitch + мок composite)")

    prefix = f"{S3_PREFIX}/{task_id}"
    schema_key = f"{prefix}/L1_crops/schema_x2.png"

    # Собираем rooms для stitch
    stitch_rooms = []
    for room in analysis["rooms"]:
        safe_name = room["name"].replace(" ", "_").replace("/", "-")
        stitch_rooms.append({
            "name": room["name"],
            "polygon": room["polygon"],
            "ref_s3_key": f"{prefix}/L2_references/{safe_name}.png",
        })

    t0 = time.monotonic()
    r = requests.post(f"{IMAGE_SERVICE_URL}/stitch", json={
        "task_id": task_id,
        "schema_s3_key": schema_key,
        "rooms": stitch_rooms,
    }, timeout=30)
    dt = round(time.monotonic() - t0, 1)
    check("L4 /stitch", r.status_code == 200, f"{dt}s, stitched_key={r.json().get('stitched_key', '?')}")

    # composite — мок
    s3_put(f"{prefix}/L4_composite/composite.png", TINY_PNG_BYTES)
    check("L4 composite.png (мок)", True, "saved")


# ============================================================
# ШАГ 5: ВАЛИДАЦИЯ S3 СТРУКТУРЫ
# ============================================================

def step5_validate(analysis):
    """Проверяем что все файлы на месте с правильной структурой."""
    print("\n📦 Шаг 5: Валидация S3 структуры")

    prefix = f"{S3_PREFIX}/{task_id}"
    all_files = s3_list(f"{prefix}/")
    all_keys = [k for k, _ in all_files]
    rooms_count = len(analysis["rooms"])

    # root
    check("meta.json", any("meta.json" in k and "L1" not in k for k in all_keys))

    # L1
    l1 = [k for k in all_keys if "L1_crops" in k]
    check("L1 schema_x2.png", any("schema_x2.png" in k for k in l1))
    check("L1 analysis.json", any("analysis.json" in k for k in l1))
    check("L1 L1_meta.json", any("L1_meta.json" in k for k in l1))
    check("L1 schema_with_polygons.png", any("schema_with_polygons" in k for k in l1))
    crops = [k for k in l1 if "crop.png" in k]
    check(f"L1 crops == {rooms_count}", len(crops) == rooms_count, f"found {len(crops)}")

    # L2
    l2 = [k for k in all_keys if "L2_references" in k]
    check(f"L2 references == {rooms_count}", len(l2) == rooms_count, f"found {len(l2)}")

    # L3
    l3 = [k for k in all_keys if "L3_renders" in k]
    prepared = [k for k in l3 if "prepared" in k]
    sides_a = [k for k in l3 if "side_a" in k]
    sides_b = [k for k in l3 if "side_b" in k]
    check(f"L3 prepared == {rooms_count * 2}", len(prepared) == rooms_count * 2, f"found {len(prepared)}")
    check(f"L3 side_a == {rooms_count}", len(sides_a) == rooms_count, f"found {len(sides_a)}")
    check(f"L3 side_b == {rooms_count}", len(sides_b) == rooms_count, f"found {len(sides_b)}")

    # L4
    l4 = [k for k in all_keys if "L4_composite" in k]
    check("L4 stitched.png", any("stitched.png" in k for k in l4))
    check("L4 composite.png", any("composite.png" in k for k in l4))

    # Общий счёт
    # root(1) + L1(4 + rooms) + L2(rooms) + L3(rooms*4) + L4(2)
    expected = 1 + (4 + rooms_count) + rooms_count + (rooms_count * 4) + 2
    check(f"Total files == {expected}", len(all_files) == expected, f"found {len(all_files)}")

    print(f"\n  Файлы по слоям: L1={len(l1)} L2={len(l2)} L3={len(l3)} L4={len(l4)} root=1")


# ============================================================
# ШАГ 6: CLEANUP
# ============================================================

def step6_cleanup():
    """Удаляем все тестовые файлы из S3."""
    print("\n🧹 Шаг 6: Cleanup")

    prefix = f"{S3_PREFIX}/{task_id}/"
    objects = s3_list(prefix)
    if objects:
        s3.delete_objects(
            Bucket=S3_BUCKET,
            Delete={"Objects": [{"Key": k} for k, _ in objects]},
        )
    remaining = s3_list(prefix)
    check(f"Cleanup ({len(objects)} deleted)", len(remaining) == 0, f"remaining={len(remaining)}")


# ============================================================
# ВАЛИДАЦИЯ СУЩЕСТВУЮЩЕЙ ЗАДАЧИ
# ============================================================

def validate_existing(existing_task_id):
    """Валидация существующей задачи без нового прогона."""
    global task_id
    task_id = existing_task_id

    prefix = f"{S3_PREFIX}/{task_id}"

    # Скачиваем analysis чтобы знать rooms_count
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key=f"{prefix}/L1_crops/analysis.json")
        analysis = json.loads(resp["Body"].read())
    except Exception as e:
        print(f"  ❌ Не удалось скачать analysis.json: {e}")
        sys.exit(1)

    step5_validate(analysis)


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="E2E smoke-тест пайплайна")
    parser.add_argument("--task-id", help="Валидация существующей задачи")
    parser.add_argument("--no-cleanup", action="store_true", help="Не удалять артефакты после теста")
    args = parser.parse_args()

    print("=" * 60)
    print("  FSK Generate Image — E2E Pipeline Smoke Test")
    print("=" * 60)

    if args.task_id:
        print(f"\n  Режим: валидация существующего task_id={args.task_id}")
        validate_existing(args.task_id)
    else:
        # Проверяем фикстуры
        if not os.path.exists(TEST_PLAN_PATH):
            print(f"  ❌ Фикстура не найдена: {TEST_PLAN_PATH}")
            sys.exit(1)
        if not os.path.exists(TEST_ANALYSIS_PATH):
            print(f"  ❌ Фикстура не найдена: {TEST_ANALYSIS_PATH}")
            sys.exit(1)

        # Полный прогон
        analysis = step1_layer1()
        step2_layer2(analysis)
        step3_layer3(analysis)
        step4_layer4(analysis)
        step5_validate(analysis)

        if not args.no_cleanup:
            step6_cleanup()
        else:
            print(f"\n  ⏭  Cleanup пропущен (--no-cleanup). task_id={task_id}")

    # Итог
    passed = sum(1 for _, ok in results if ok)
    failed = sum(1 for _, ok in results if not ok)
    total = len(results)

    print("\n" + "=" * 60)
    if failed == 0:
        print(f"  ✅ PASS — {passed}/{total} проверок")
    else:
        print(f"  ❌ FAIL — {failed} из {total}:")
        for name, ok in results:
            if not ok:
                print(f"     - {name}")
    if task_id:
        print(f"  task_id: {task_id}")
    print("=" * 60)

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
