"""
Конфигурация логирования для всего проекта.

Логгеры по компонентам:
    fsk.api      — входящие запросы, валидация, эндпоинты
    fsk.pipeline — прогресс пайплайна, обработка комнат
    fsk.layer1   — анализ планировки
    fsk.layer2   — генерация референса (вид сверху)
    fsk.layer3   — рендер из угловых ракурсов (2 стороны)
    fsk.layer4   — общий рендер квартиры
    fsk.session  — управление сессиями юзеров

Два хэндлера:
    - Консоль (stdout) — для отладки
    - Файл (logs/app.log) — для хранения, ротация 10 МБ, 5 файлов

Формат: "2026-03-23 10:15:32 | INFO | fsk.pipeline | сообщение"

Использование:
    from src.logger import get_logger
    log = get_logger("fsk.api")
    log.info("Новая задача")
    log.error("Ошибка валидации")
"""

import logging
from logging.handlers import RotatingFileHandler
import os

# Папка логов
LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

# Формат логов
LOG_FORMAT = "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Флаг — настроено ли уже логирование
_configured = False


def _setup() -> None:
    """Настраивает корневой логгер fsk один раз."""
    global _configured
    if _configured:
        return

    # Корневой логгер проекта
    root = logging.getLogger("fsk")
    root.setLevel(logging.DEBUG)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # Консоль
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    root.addHandler(console)

    # Файл с ротацией (10 МБ, хранить 5 файлов)
    log_file = os.path.join(LOGS_DIR, "app.log")
    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Возвращает логгер по имени компонента.

    Принимает:
        name — имя логгера (например "fsk.api", "fsk.layer1")

    Возвращает:
        logging.Logger с настроенными хэндлерами
    """
    _setup()
    return logging.getLogger(name)
