"""
Конфигурация проекта — ключи API, URL-ы, модели.

Все секреты читаются из переменных окружения.
Для локальной разработки: создать .env файл (см. .env.example).
"""

import os

# Загружаем .env если есть (для локальной разработки)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv не установлен — ок, читаем из системных env

# Gemini 3 Flash для анализа планировок (Слой 1)
LAYER1_MODEL = os.getenv("LAYER1_MODEL", "google/gemini-3-flash-preview")

# OpenRouter API (Gemini для генерации изображений)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "google/gemini-3.1-flash-image-preview")

# OSMI (Flowise) эндпоинты
OSMI_LAYER1_URL = os.getenv("OSMI_LAYER1_URL", "https://app.osmi-ai.ru/api/v1/prediction/ffe02989-9afc-4f3f-a054-e9210ccadf43")
OSMI_LAYER2_URL = os.getenv("OSMI_LAYER2_URL", "https://app.osmi-ai.ru/api/v1/prediction/c86d4578-b9b7-4080-b689-dc08c6657c7f")

# API-ключ для авторизации фронта
FSK_API_KEY = os.getenv("FSK_API_KEY", "")

# Параметры генерации
LAYER1_TEMPERATURE = 0.2
LAYER1_IMAGE_DETAIL = "high"
