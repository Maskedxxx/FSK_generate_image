#!/bin/bash
# ============================================
# Health Check + Smoke Test + Telegram алерт
# FSK Image Service + OSMI Pipeline
#
# Запуск через cron каждые 5 минут:
#   */5 * * * * /path/to/scripts/healthcheck.sh
#
# Логика:
#   1. curl /health — Python-сервис жив?
#   2. curl /smoke — S3 доступен?
#   3. curl OSMI /health — OSMI платформа жива?
#   4. curl OpenRouter /auth/key — кредиты есть?
#   5. Если упало и флаг НЕ стоит → алерт + ставим флаг
#   6. Если всё ок и флаг стоит → алерт "восстановлено"
# ============================================

# --- Конфигурация ---
PYTHON_URL="https://llm-home.fsk.fvds.ru"
OSMI_URL="https://app.osmi-ai.ru"
FLAG_FILE="/tmp/fsk_alert_sent"
TIMEOUT=15

# Telegram (из .env рядом с docker-compose)
# Путь: osmi_nodes/scripts/ → корень проекта (3 уровня)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ENV_FILE="$PROJECT_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    TELEGRAM_BOT_TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | cut -d'=' -f2-)
    TELEGRAM_CHAT_ID=$(grep -E '^TELEGRAM_CHAT_ID=' "$ENV_FILE" | cut -d'=' -f2-)
fi

# Хардкод OpenRouter ключ для проверки кредитов
OPENROUTER_KEY="<OPENROUTER_API_KEY>"

if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_CHAT_ID" ]; then
    exit 0
fi

# --- Функция отправки в Telegram ---
send_telegram() {
    local message="$1"
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" \
        -d "text=${message}" \
        > /dev/null 2>&1
}

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
ERRORS=""

# --- Phase 1: Python Image Service ---
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "$PYTHON_URL/health" 2>/dev/null)
if [ "$HTTP_CODE" != "200" ]; then
    ERRORS="${ERRORS}\n- Python Service недоступен (HTTP $HTTP_CODE)"
fi

# --- Phase 2: S3 через /smoke ---
if [ "$HTTP_CODE" = "200" ]; then
    SMOKE_STATUS=$(curl -s --max-time "$TIMEOUT" "$PYTHON_URL/smoke" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null)
    if [ "$SMOKE_STATUS" != "ok" ]; then
        ERRORS="${ERRORS}\n- S3 недоступен (smoke: $SMOKE_STATUS)"
    fi
fi

# --- Phase 3: OSMI платформа ---
OSMI_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "$OSMI_URL" 2>/dev/null)
if [ "$OSMI_CODE" != "200" ]; then
    ERRORS="${ERRORS}\n- OSMI платформа недоступна (HTTP $OSMI_CODE)"
fi

# --- Phase 4: OpenRouter кредиты ---
CREDITS_OK=$(curl -s --max-time "$TIMEOUT" -H "Authorization: Bearer $OPENROUTER_KEY" "https://openrouter.ai/api/v1/auth/key" 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin).get('data', {})
    limit = d.get('limit')
    usage = d.get('usage', 0)
    if limit is not None and usage >= limit:
        print('exhausted')
    else:
        print('ok')
except:
    print('error')
" 2>/dev/null)
if [ "$CREDITS_OK" = "exhausted" ]; then
    ERRORS="${ERRORS}\n- OpenRouter кредиты закончились"
elif [ "$CREDITS_OK" = "error" ]; then
    ERRORS="${ERRORS}\n- OpenRouter API недоступен"
fi

# --- Вердикт ---
if [ -n "$ERRORS" ]; then
    if [ ! -f "$FLAG_FILE" ]; then
        send_telegram "$(printf '\xe2\x9d\x8c') FSK Image Service: проблемы
Компоненты:$(echo -e "$ERRORS")
Время: $TIMESTAMP
Действие: проверить docker ps, логи, Yandex Object Storage"
        touch "$FLAG_FILE"
    fi
    exit 1
fi

# Всё работает
if [ -f "$FLAG_FILE" ]; then
    send_telegram "$(printf '\xe2\x9c\x85') FSK Image Service: восстановлено
Все компоненты работают
Время: $TIMESTAMP"
    rm -f "$FLAG_FILE"
fi
