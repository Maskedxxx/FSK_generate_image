"""
Абстракция хранилища — единый интерфейс для Local и S3.

Весь код работает через StorageBackend — не знает где физически лежат файлы.
Переключение local → S3 = одна переменная STORAGE_BACKEND в .env.

Классы:
    StorageBackend          — ABC интерфейс
    LocalStorageBackend     — файловая система (dev/тесты)
    S3StorageBackend        — Yandex Object Storage / AWS S3 (прод)

Фабрика:
    create_storage()        — выбирает реализацию по конфигу
"""

import json
import os
import shutil
from abc import ABC, abstractmethod

from .logger import get_logger

log = get_logger("fsk.storage")


class StorageBackend(ABC):
    """Интерфейс хранилища — все операции с файлами через него."""

    @abstractmethod
    def write_bytes(self, key: str, data: bytes) -> None:
        ...

    @abstractmethod
    def write_json(self, key: str, data: dict) -> None:
        ...

    @abstractmethod
    def read_bytes(self, key: str) -> bytes:
        ...

    @abstractmethod
    def read_json(self, key: str) -> dict:
        ...

    @abstractmethod
    def exists(self, key: str) -> bool:
        ...

    @abstractmethod
    def list_keys(self, prefix: str) -> list[str]:
        ...

    @abstractmethod
    def delete_prefix(self, prefix: str) -> bool:
        ...

    @abstractmethod
    def presigned_url(self, key: str, expires: int = 3600) -> str:
        ...


# === LOCAL ===


class LocalStorageBackend(StorageBackend):
    """Хранилище на файловой системе — для разработки и тестов."""

    def __init__(self, base_path: str = "results"):
        self.base_path = base_path
        os.makedirs(base_path, exist_ok=True)
        log.info(f"LocalStorage: {base_path}")

    def _full_path(self, key: str) -> str:
        return os.path.join(self.base_path, key)

    def write_bytes(self, key: str, data: bytes) -> None:
        path = self._full_path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    def write_json(self, key: str, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.write_bytes(key, body)

    def read_bytes(self, key: str) -> bytes:
        path = self._full_path(key)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Файл не найден: {key}")
        with open(path, "rb") as f:
            return f.read()

    def read_json(self, key: str) -> dict:
        data = self.read_bytes(key)
        return json.loads(data.decode("utf-8"))

    def exists(self, key: str) -> bool:
        return os.path.exists(self._full_path(key))

    def list_keys(self, prefix: str) -> list[str]:
        base = self._full_path(prefix)
        if not os.path.exists(base):
            return []
        keys = []
        for root, dirs, files in os.walk(base):
            for fname in files:
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, self.base_path)
                keys.append(rel)
        keys.sort()
        return keys

    def delete_prefix(self, prefix: str) -> bool:
        path = self._full_path(prefix)
        if not os.path.exists(path):
            return False
        shutil.rmtree(path)
        return True

    def presigned_url(self, key: str, expires: int = 3600) -> str:
        # Локально — просто путь к файлу через /files/
        return f"/files/{key}"


# === S3 ===


class S3StorageBackend(StorageBackend):
    """Хранилище в S3 (Yandex Object Storage) — для прода."""

    def __init__(self, bucket: str, endpoint_url: str, region: str,
                 access_key_id: str, secret_access_key: str, prefix: str = ""):
        self.bucket = bucket
        self.endpoint_url = endpoint_url
        self.region = region
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.prefix = prefix.strip("/")
        self._client = None
        log.info(f"S3Storage: bucket={bucket}, prefix={self.prefix}, endpoint={endpoint_url}")

    def _full_key(self, key: str) -> str:
        """Добавляет префикс сервиса к ключу."""
        if self.prefix:
            return f"{self.prefix}/{key}"
        return key

    def _get_client(self):
        """Lazy init — клиент создаётся при первом вызове."""
        if self._client is None:
            import boto3
            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                region_name=self.region,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
            )
        return self._client

    def write_bytes(self, key: str, data: bytes) -> None:
        client = self._get_client()
        client.put_object(Bucket=self.bucket, Key=self._full_key(key), Body=data)

    def write_json(self, key: str, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        client = self._get_client()
        client.put_object(
            Bucket=self.bucket, Key=self._full_key(key), Body=body,
            ContentType="application/json",
        )

    def read_bytes(self, key: str) -> bytes:
        client = self._get_client()
        try:
            response = client.get_object(Bucket=self.bucket, Key=self._full_key(key))
            return response["Body"].read()
        except client.exceptions.NoSuchKey:
            raise FileNotFoundError(f"Объект не найден в S3: {key}")

    def read_json(self, key: str) -> dict:
        data = self.read_bytes(key)
        return json.loads(data.decode("utf-8"))

    def exists(self, key: str) -> bool:
        client = self._get_client()
        try:
            client.head_object(Bucket=self.bucket, Key=self._full_key(key))
            return True
        except Exception:
            return False

    def list_keys(self, prefix: str) -> list[str]:
        client = self._get_client()
        full_prefix = self._full_key(prefix)
        keys = []
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=full_prefix):
            for obj in page.get("Contents", []):
                # Убираем префикс сервиса из ключей
                k = obj["Key"]
                if self.prefix and k.startswith(self.prefix + "/"):
                    k = k[len(self.prefix) + 1:]
                keys.append(k)
        keys.sort()
        return keys

    def delete_prefix(self, prefix: str) -> bool:
        client = self._get_client()
        full_prefix = self._full_key(prefix)
        # Получаем полные ключи для удаления
        raw_keys = []
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=full_prefix):
            for obj in page.get("Contents", []):
                raw_keys.append(obj["Key"])
        if not raw_keys:
            return False
        for i in range(0, len(raw_keys), 1000):
            batch = raw_keys[i:i + 1000]
            client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": k} for k in batch]},
            )
        log.info(f"Удалено {len(raw_keys)} объектов по префиксу {prefix}")
        return True

    def presigned_url(self, key: str, expires: int = 3600) -> str:
        client = self._get_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._full_key(key)},
            ExpiresIn=expires,
        )


# === ФАБРИКА ===


_storage_instance = None


def create_storage() -> StorageBackend:
    """Создаёт хранилище по конфигу. Singleton — один экземпляр на приложение."""
    global _storage_instance
    if _storage_instance is not None:
        return _storage_instance

    from .config import (
        STORAGE_BACKEND, S3_BUCKET, S3_ENDPOINT_URL,
        S3_REGION, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_PREFIX,
    )

    if STORAGE_BACKEND == "s3":
        _storage_instance = S3StorageBackend(
            bucket=S3_BUCKET,
            endpoint_url=S3_ENDPOINT_URL,
            region=S3_REGION,
            access_key_id=S3_ACCESS_KEY_ID,
            secret_access_key=S3_SECRET_ACCESS_KEY,
            prefix=S3_PREFIX,
        )
    else:
        _storage_instance = LocalStorageBackend(base_path="results")

    return _storage_instance
