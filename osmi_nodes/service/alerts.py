"""
Модуль отправки алертов в Telegram.

Sync-версия для FastAPI (image_service.py) + endpoint /alert для JS-нод OSMI.
Если TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы — алерты тихо пропускаются.

Использование из Python:
    from alerts import send_alert
    send_alert("Ошибка в /upscale\nОшибка: ...", level="error")

Использование из JS-нод OSMI:
    axios.post('https://llm-home.fsk.fvds.ru/alert', {
        layer: 3, node: 'render_sides', task_id: '...', error: '...'
    })
"""

import html
import logging
import os
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

# Конфигурация Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Название приложения в алертах
_APP_NAME = "FSK Image Service"

# Иконки по уровню
_ICONS = {
    "error": "\u274c",          # ❌
    "warning": "\u26a0\ufe0f",  # ⚠️
    "info": "\u2139\ufe0f",     # ℹ️
    "recovery": "\u2705",       # ✅
}

# Таймаут HTTP запроса к Telegram API
_TIMEOUT = 10


def send_alert(message: str, level: str = "error") -> bool:
    """
    Отправляет алерт в Telegram (синхронно).

    Не бросает исключений — при ошибке логирует warning.
    Если токен/chat_id не заданы — тихо пропускает.

    Формат message:
        "Что случилось\\nСервис: X → Y\\nОшибка: Z\\nПоследствие: W"

    Returns:
        True если отправлено, False если нет.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug("[alerts] Telegram не настроен, алерт пропущен")
        return False

    icon = _ICONS.get(level, _ICONS["error"])
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Экранируем HTML-сущности — без этого Telegram ломается на <, >, &
    safe_message = html.escape(message)
    text = f"{icon} <b>{_APP_NAME}</b>\n{safe_message}\nВремя: {timestamp}"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }

    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            response = client.post(url, json=payload)

        if response.status_code == 200:
            logger.info(f"[alerts] Алерт отправлен: {level}")
            return True
        else:
            logger.warning(f"[alerts] Telegram API: {response.status_code}: {response.text[:200]}")
            return False
    except Exception as e:
        # Алерт не должен ломать основной поток
        logger.warning(f"[alerts] Ошибка отправки: {e}")
        return False
