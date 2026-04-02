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

# OSMI эндпоинты
# FSK_Layer1_TextAnalysis — текстовый анализ (Gemini Flash)
OSMI_LAYER1_URL = os.getenv("OSMI_LAYER1_URL", "")
# FSK_Layer2_ImageGen — генерация картинки с 1 изображением (Gemini Image)
OSMI_LAYER2_URL = os.getenv("OSMI_LAYER2_URL", "")
# FSK_Layer2_ImageGen_Dual — генерация картинки с 2 изображениями (Gemini Image)
OSMI_LAYER2_DUAL_URL = os.getenv("OSMI_LAYER2_DUAL_URL", "")

# API-ключ для авторизации фронта
FSK_API_KEY = os.getenv("FSK_API_KEY", "")

# Хранилище: "local" (файловая система) или "s3" (Yandex Object Storage)
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")
# Корневой префикс в S3 (папка сервиса в бакете)
S3_PREFIX = os.getenv("S3_PREFIX", "fsk-generate-image")

# S3 (Yandex Object Storage)
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "https://storage.yandexcloud.net")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
S3_BUCKET = os.getenv("S3_BUCKET", "")
S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID", "")
S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY", "")

# Параметры генерации
LAYER1_TEMPERATURE = 0.2
LAYER1_IMAGE_DETAIL = "high"
