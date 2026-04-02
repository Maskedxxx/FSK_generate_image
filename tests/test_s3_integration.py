"""
Интеграционные тесты S3 хранилища + task_manager.

Работают с реальным S3 (Yandex Object Storage).
Все тестовые данные в префиксе _test_s3/ — чистятся после прогона.

Запуск: python tests/test_s3_integration.py
"""

import sys
import os
import json
import time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Сброс singleton для чистого старта
import src.storage as storage_module
storage_module._storage_instance = None

from src.storage import create_storage
from src import task_manager

TEST_PREFIX = "_test_s3"
PASSED = 0
FAILED = 0


def ok(name: str):
    global PASSED
    PASSED += 1
    print(f"  ✓ {name}")


def fail(name: str, error: str):
    global FAILED
    FAILED += 1
    print(f"  ✗ {name}: {error}")


def cleanup(s):
    """Удаляет все тестовые данные."""
    s.delete_prefix(f"{TEST_PREFIX}/")


def test_write_read_bytes(s):
    """1. write_bytes + read_bytes — записать, прочитать, сравнить."""
    key = f"{TEST_PREFIX}/bytes_test.png"
    data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # Псевдо-PNG
    s.write_bytes(key, data)
    result = s.read_bytes(key)
    assert result == data, f"Данные не совпадают: {len(result)} != {len(data)}"
    ok("write_bytes + read_bytes")


def test_write_read_json(s):
    """2. write_json + read_json — записать dict, прочитать, сравнить."""
    key = f"{TEST_PREFIX}/json_test.json"
    data = {"rooms": [{"name": "Кухня", "area": 13.4}], "total": 1}
    s.write_json(key, data)
    result = s.read_json(key)
    assert result == data, f"JSON не совпадает: {result}"
    ok("write_json + read_json")


def test_read_bytes_not_found(s):
    """3. read_bytes несуществующего ключа → FileNotFoundError."""
    try:
        s.read_bytes(f"{TEST_PREFIX}/nonexistent_file.bin")
        fail("read_bytes FileNotFoundError", "Исключение не выброшено")
    except FileNotFoundError:
        ok("read_bytes FileNotFoundError")


def test_read_json_not_found(s):
    """4. read_json несуществующего ключа → FileNotFoundError."""
    try:
        s.read_json(f"{TEST_PREFIX}/nonexistent.json")
        fail("read_json FileNotFoundError", "Исключение не выброшено")
    except FileNotFoundError:
        ok("read_json FileNotFoundError")


def test_exists_before_write(s):
    """5. exists → False до записи."""
    result = s.exists(f"{TEST_PREFIX}/not_yet.txt")
    assert result is False, f"Ожидали False, получили {result}"
    ok("exists → False до записи")


def test_exists_after_write(s):
    """6. exists → True после записи."""
    key = f"{TEST_PREFIX}/exists_test.txt"
    s.write_bytes(key, b"hello")
    result = s.exists(key)
    assert result is True, f"Ожидали True, получили {result}"
    ok("exists → True после записи")


def test_exists_after_delete(s):
    """7. exists → False после удаления."""
    key = f"{TEST_PREFIX}/delete_me.txt"
    s.write_bytes(key, b"bye")
    s.delete_prefix(f"{TEST_PREFIX}/delete_me")
    result = s.exists(key)
    assert result is False, f"Ожидали False после удаления, получили {result}"
    ok("exists → False после удаления")


def test_list_keys(s):
    """8. list_keys — записать 3 файла, получить список."""
    prefix = f"{TEST_PREFIX}/list_test"
    s.write_bytes(f"{prefix}/a.png", b"a")
    s.write_bytes(f"{prefix}/b.png", b"b")
    s.write_bytes(f"{prefix}/sub/c.png", b"c")
    keys = s.list_keys(prefix)
    assert len(keys) == 3, f"Ожидали 3 ключа, получили {len(keys)}: {keys}"
    ok("list_keys — 3 файла")


def test_list_keys_empty(s):
    """9. list_keys пустого префикса → пустой список."""
    keys = s.list_keys(f"{TEST_PREFIX}/empty_prefix_xxx/")
    assert keys == [], f"Ожидали пустой список, получили {keys}"
    ok("list_keys пустого префикса")


def test_delete_prefix(s):
    """10. delete_prefix — записать, удалить, проверить что пусто."""
    prefix = f"{TEST_PREFIX}/del_test"
    s.write_bytes(f"{prefix}/1.txt", b"1")
    s.write_bytes(f"{prefix}/2.txt", b"2")
    s.write_bytes(f"{prefix}/sub/3.txt", b"3")
    result = s.delete_prefix(f"{prefix}/")
    assert result is True, "delete_prefix вернул False"
    keys = s.list_keys(f"{prefix}/")
    assert keys == [], f"После удаления осталось: {keys}"
    ok("delete_prefix — всё удалено")


def test_delete_prefix_empty(s):
    """11. delete_prefix пустого префикса → False."""
    result = s.delete_prefix(f"{TEST_PREFIX}/nothing_here_xxx/")
    assert result is False, f"Ожидали False, получили {result}"
    ok("delete_prefix пустого → False")


def test_presigned_url(s):
    """12. presigned_url — записать, получить URL, скачать, сравнить."""
    key = f"{TEST_PREFIX}/url_test.json"
    data = {"test": "presigned"}
    s.write_json(key, data)
    url = s.presigned_url(key, expires=300)
    assert "storage.yandexcloud.net" in url, f"URL не содержит endpoint: {url}"

    # Скачиваем по URL
    resp = requests.get(url, timeout=10)
    assert resp.status_code == 200, f"HTTP {resp.status_code} при скачивании"
    downloaded = resp.json()
    assert downloaded == data, f"Скачанные данные не совпадают: {downloaded}"
    ok("presigned_url — запись, URL, скачивание")


def test_prefix_in_real_key(s):
    """13. Проверяем что реальный ключ в S3 содержит префикс сервиса."""
    from src.storage import S3StorageBackend
    if not isinstance(s, S3StorageBackend):
        ok("prefix — пропущен (не S3)")
        return

    key = f"{TEST_PREFIX}/prefix_check.txt"
    s.write_bytes(key, b"check")
    full_key = s._full_key(key)
    assert "fsk-generate-image" in full_key, f"Префикс не найден в ключе: {full_key}"

    # Проверяем через boto3 напрямую
    client = s._get_client()
    resp = client.head_object(Bucket=s.bucket, Key=full_key)
    assert resp["ResponseMetadata"]["HTTPStatusCode"] == 200
    ok("prefix в реальном S3 ключе")


# === TASK MANAGER ===


def test_create_get_task(s):
    """14. create_task → get_task → status == processing."""
    tid = f"{TEST_PREFIX}/task_create"
    task_manager.create_task(s, tid, {"style": "Скандинавский"})
    task = task_manager.get_task(s, tid)
    assert task is not None, "Задача не найдена"
    assert task["status"] == "processing", f"Статус: {task['status']}"
    assert task["answers"]["style"] == "Скандинавский"
    ok("create_task + get_task")


def test_update_progress(s):
    """15. update_progress → get_task → progress обновился."""
    tid = f"{TEST_PREFIX}/task_progress"
    task_manager.create_task(s, tid)
    task_manager.update_progress(s, tid, "Слой 1 готов: 5 комнат")
    task = task_manager.get_task(s, tid)
    assert task["progress"] == "Слой 1 готов: 5 комнат"
    ok("update_progress")


def test_complete_task(s):
    """16. complete_task → status == done, result есть."""
    tid = f"{TEST_PREFIX}/task_done"
    task_manager.create_task(s, tid)
    result = {"rooms_count": 3, "rooms": []}
    task_manager.complete_task(s, tid, result)
    task = task_manager.get_task(s, tid)
    assert task["status"] == "done"
    assert task["result"]["rooms_count"] == 3
    ok("complete_task")


def test_fail_task(s):
    """17. fail_task → status == error."""
    tid = f"{TEST_PREFIX}/task_error"
    task_manager.create_task(s, tid)
    task_manager.fail_task(s, tid, "OSMI нода недоступна")
    task = task_manager.get_task(s, tid)
    assert task["status"] == "error"
    assert "OSMI" in task["error"]
    ok("fail_task")


def test_get_task_not_found(s):
    """18. get_task несуществующего → None."""
    result = task_manager.get_task(s, f"{TEST_PREFIX}/no_such_task_xxx")
    assert result is None, f"Ожидали None, получили {result}"
    ok("get_task → None для несуществующего")


def test_cleanup_old_tasks(s):
    """19. cleanup — старая удалена, свежая осталась."""
    # Создаём «старую» задачу (вручную ставим timestamp в прошлое)
    old_tid = f"{TEST_PREFIX}/task_old"
    s.write_json(f"{old_tid}/status.json", {
        "status": "done",
        "created_at": "2020-01-01T00:00:00+00:00",
        "progress": "Готово",
    })
    s.write_bytes(f"{old_tid}/dummy.png", b"old data")

    # Создаём свежую задачу
    new_tid = f"{TEST_PREFIX}/task_new"
    task_manager.create_task(s, new_tid)
    s.write_bytes(f"{new_tid}/dummy.png", b"new data")

    # Cleanup
    deleted = task_manager.cleanup_old_tasks(s, max_age_hours=1)
    assert deleted >= 1, f"Ожидали удаление ≥1, удалено {deleted}"

    # Старая удалена
    assert not s.exists(f"{old_tid}/status.json"), "Старая задача не удалена"
    assert not s.exists(f"{old_tid}/dummy.png"), "Файлы старой задачи не удалены"

    # Свежая осталась
    assert s.exists(f"{new_tid}/status.json"), "Свежая задача удалена!"
    ok("cleanup_old_tasks")


# === ЗАПУСК ===


def main():
    print("\n=== Интеграционные тесты S3 ===\n")

    s = create_storage()
    print(f"Backend: {type(s).__name__}")
    if hasattr(s, 'prefix'):
        print(f"Prefix: {s.prefix}")
    print()

    # Cleanup перед тестами
    cleanup(s)

    tests = [
        test_write_read_bytes,
        test_write_read_json,
        test_read_bytes_not_found,
        test_read_json_not_found,
        test_exists_before_write,
        test_exists_after_write,
        test_exists_after_delete,
        test_list_keys,
        test_list_keys_empty,
        test_delete_prefix,
        test_delete_prefix_empty,
        test_presigned_url,
        test_prefix_in_real_key,
        test_create_get_task,
        test_update_progress,
        test_complete_task,
        test_fail_task,
        test_get_task_not_found,
        test_cleanup_old_tasks,
    ]

    for test in tests:
        try:
            test(s)
        except Exception as e:
            fail(test.__doc__ or test.__name__, str(e))

    # Cleanup после тестов
    cleanup(s)

    print(f"\n{'='*40}")
    print(f"Итого: {PASSED} прошло, {FAILED} упало")
    if FAILED:
        sys.exit(1)
    print("Все тесты пройдены!")


if __name__ == "__main__":
    main()
