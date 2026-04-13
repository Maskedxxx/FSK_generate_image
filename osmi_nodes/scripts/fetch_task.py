"""
Просмотр и скачивание артефактов задачи по task_id.

Самодостаточный скрипт — креды S3 захардкожены, зависит только от boto3.

Использование:
    python scripts/fetch_task.py 2026-04-08_abc12345              # ссылки в терминале
    python scripts/fetch_task.py 2026-04-08_abc12345 --download   # скачать в ./results/<task_id>/
    python scripts/fetch_task.py 2026-04-08_abc12345 --open       # открыть composite.png в браузере
"""

import argparse
import os
import sys
import webbrowser
from pathlib import Path

import boto3


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

# === КРЕДЫ S3 (из .env) ===
S3_ENDPOINT_URL = "https://storage.yandexcloud.net"
S3_REGION = "us-east-1"
S3_BUCKET = os.environ.get("S3_BUCKET", "fsk-service")
S3_PREFIX = os.environ.get("S3_PREFIX", "fsk-generate-image")
S3_ACCESS_KEY_ID = os.environ["S3_ACCESS_KEY_ID"]
S3_SECRET_ACCESS_KEY = os.environ["S3_SECRET_ACCESS_KEY"]

# Время жизни presigned URL — 1 час
URL_EXPIRES = 3600

# Иконки для красивого вывода
ICONS = {".png": "🖼️ ", ".jpg": "🖼️ ", ".jpeg": "🖼️ ", ".json": "📄"}

# Порядок слоёв для группировки
LAYER_ORDER = ["", "L1_crops", "L2_references", "L3_renders", "L4_composite"]


def get_s3_client():
    """Создаёт S3 клиент Yandex Object Storage."""
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT_URL,
        region_name=S3_REGION,
        aws_access_key_id=S3_ACCESS_KEY_ID,
        aws_secret_access_key=S3_SECRET_ACCESS_KEY,
    )


def list_task_files(s3, task_id: str) -> list[str]:
    """Листит все ключи задачи в S3. Возвращает сортированный список."""
    prefix = f"{S3_PREFIX}/{task_id}/"
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return sorted(keys)


def group_by_layer(keys: list[str], task_id: str) -> dict[str, list[str]]:
    """Группирует ключи по слоям (L1_crops / L2_references / L3_renders / L4_composite / корень)."""
    groups = {layer: [] for layer in LAYER_ORDER}
    prefix = f"{S3_PREFIX}/{task_id}/"

    for key in keys:
        rel = key[len(prefix):]  # убираем префикс, остаётся L1_crops/file.png или file.json
        if "/" in rel:
            layer, _ = rel.split("/", 1)
            if layer in groups:
                groups[layer].append(key)
            else:
                groups.setdefault("", []).append(key)
        else:
            groups[""].append(key)

    return groups


def view_mode(task_id: str):
    """Печатает все файлы задачи с presigned URLs, сгруппированные по слоям."""
    s3 = get_s3_client()
    keys = list_task_files(s3, task_id)

    if not keys:
        print(f"❌ Задача не найдена: {task_id}")
        print(f"   Префикс: s3://{S3_BUCKET}/{S3_PREFIX}/{task_id}/")
        sys.exit(1)

    print(f"\n📦 Task: {task_id}")
    print(f"   {len(keys)} файлов в S3\n")

    groups = group_by_layer(keys, task_id)

    for layer in LAYER_ORDER:
        layer_keys = groups.get(layer, [])
        if not layer_keys:
            continue

        label = layer if layer else "(корень задачи)"
        print(f"  {label}/  ({len(layer_keys)} файлов)")

        for key in layer_keys:
            fname = key.rsplit("/", 1)[-1]
            ext = os.path.splitext(fname)[1].lower()
            icon = ICONS.get(ext, "  ")

            # Presigned URL — валиден 1 час
            url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": S3_BUCKET, "Key": key},
                ExpiresIn=URL_EXPIRES,
            )
            print(f"    {icon} {fname}")
            print(f"       {url}")
        print()


def download_mode(task_id: str):
    """Скачивает все артефакты в ./results/<task_id>/ с сохранением структуры."""
    s3 = get_s3_client()
    keys = list_task_files(s3, task_id)

    if not keys:
        print(f"❌ Задача не найдена: {task_id}")
        sys.exit(1)

    out_dir = os.path.join("results", task_id)
    os.makedirs(out_dir, exist_ok=True)
    prefix = f"{S3_PREFIX}/{task_id}/"

    print(f"\n📥 Скачиваю {len(keys)} файлов в {out_dir}/\n")

    for key in keys:
        rel = key[len(prefix):]
        local_path = os.path.join(out_dir, rel)
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        s3.download_file(S3_BUCKET, key, local_path)
        size_kb = os.path.getsize(local_path) // 1024
        print(f"  ✓ {rel}  ({size_kb} KB)")

    print(f"\n✅ Готово: {out_dir}/")


def open_mode(task_id: str):
    """Открывает composite.png финального слоя в браузере."""
    s3 = get_s3_client()
    composite_key = f"{S3_PREFIX}/{task_id}/L4_composite/composite.png"

    # Проверяем наличие
    try:
        s3.head_object(Bucket=S3_BUCKET, Key=composite_key)
    except Exception:
        print(f"❌ composite.png ещё не готов для задачи {task_id}")
        print(f"   Возможно Слой 4 не отработал.")
        sys.exit(1)

    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": composite_key},
        ExpiresIn=URL_EXPIRES,
    )
    print(f"🌐 Открываю composite.png в браузере...")
    print(f"   {url}")
    webbrowser.open(url)


def main():
    parser = argparse.ArgumentParser(description="Просмотр/скачивание артефактов задачи из S3")
    parser.add_argument("task_id", help="Идентификатор задачи (например 2026-04-08_abc12345)")
    parser.add_argument("--download", action="store_true", help="Скачать все файлы в ./results/<task_id>/")
    parser.add_argument("--open", action="store_true", help="Открыть composite.png в браузере")
    args = parser.parse_args()

    if args.download:
        download_mode(args.task_id)
    elif args.open:
        open_mode(args.task_id)
    else:
        view_mode(args.task_id)


if __name__ == "__main__":
    main()
