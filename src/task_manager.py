"""
Менеджер задач — статусы через S3/Local хранилище.

Заменяет in-memory tasks = {} на персистентное хранение.
Каждый воркер читает/пишет status.json через StorageBackend.

Функции:
    create_task()       — создать задачу (status: processing)
    update_progress()   — обновить прогресс
    complete_task()     — завершить (status: done)
    fail_task()         — ошибка (status: error)
    get_task()          — прочитать статус
    cleanup_old_tasks() — удалить задачи старше 24 часов
"""

from datetime import datetime, timezone, timedelta

from .storage import StorageBackend
from .logger import get_logger

log = get_logger("fsk.tasks")


def _status_key(task_id: str) -> str:
    """Ключ файла статуса в хранилище."""
    return f"{task_id}/status.json"


def create_task(storage: StorageBackend, task_id: str, answers: dict = None) -> dict:
    """Создаёт новую задачу со статусом processing."""
    status = {
        "status": "processing",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "progress": "Задача создана",
        "answers": answers or {},
        "result": None,
        "error": None,
    }
    storage.write_json(_status_key(task_id), status)
    log.info(f"[{task_id}] Задача создана")
    return status


def update_progress(storage: StorageBackend, task_id: str, message: str) -> None:
    """Обновляет прогресс задачи."""
    try:
        status = storage.read_json(_status_key(task_id))
    except FileNotFoundError:
        log.warning(f"[{task_id}] status.json не найден при обновлении прогресса")
        return
    status["progress"] = message
    storage.write_json(_status_key(task_id), status)


def complete_task(storage: StorageBackend, task_id: str, result: dict) -> None:
    """Завершает задачу — status: done."""
    try:
        status = storage.read_json(_status_key(task_id))
    except FileNotFoundError:
        status = {}
    status["status"] = "done"
    status["progress"] = "Готово"
    status["result"] = result
    storage.write_json(_status_key(task_id), status)
    log.info(f"[{task_id}] Задача завершена")


def fail_task(storage: StorageBackend, task_id: str, error: str) -> None:
    """Помечает задачу как ошибочную."""
    try:
        status = storage.read_json(_status_key(task_id))
    except FileNotFoundError:
        status = {}
    status["status"] = "error"
    status["progress"] = f"Ошибка: {error}"
    status["error"] = error
    storage.write_json(_status_key(task_id), status)
    log.error(f"[{task_id}] Задача с ошибкой: {error}")


def get_task(storage: StorageBackend, task_id: str) -> dict | None:
    """Читает статус задачи. None если не найдена."""
    try:
        return storage.read_json(_status_key(task_id))
    except FileNotFoundError:
        return None


def cleanup_old_tasks(storage: StorageBackend, max_age_hours: int = 24) -> int:
    """
    Удаляет задачи старше max_age_hours.
    Возвращает количество удалённых задач.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    deleted = 0

    # Ищем все status.json
    all_keys = storage.list_keys("")
    status_keys = [k for k in all_keys if k.endswith("/status.json")]

    for key in status_keys:
        try:
            status = storage.read_json(key)
            created = datetime.fromisoformat(status.get("created_at", ""))
            if created < cutoff:
                # Извлекаем task_id из ключа: "{task_id}/status.json"
                task_id = key.rsplit("/status.json", 1)[0]
                storage.delete_prefix(f"{task_id}/")
                deleted += 1
                log.info(f"Очистка: удалена задача {task_id}")
        except Exception as e:
            log.warning(f"Очистка: ошибка обработки {key}: {e}")

    log.info(f"Очистка завершена: удалено {deleted} задач")
    return deleted
