# Конфигурация проекта — ключи API, URL-ы, модели

# OpenAI API (запасной вариант)
OPENAI_API_KEY = "${OPENAI_API_KEY}"
OPENAI_MODEL = "gpt-4.1"

# Gemini 3 Flash для анализа планировок (Слой 1)
LAYER1_MODEL = "google/gemini-3-flash-preview"

# OpenRouter API (Gemini для генерации изображений)
OPENROUTER_API_KEY = "${OPENROUTER_API_KEY}"
GEMINI_MODEL = "google/gemini-3.1-flash-image-preview"

# OSMI (Flowise) эндпоинты
OSMI_LAYER1_URL = "https://app.osmi-it.ru/api/v1/prediction/c227250e-4a01-41d2-a90e-a1c27985ba8a"
OSMI_LAYER2_URL = "https://app.osmi-it.ru/api/v1/prediction/e88e5a7d-80fc-41bd-9ec8-42177594cea2"

# Параметры генерации
LAYER1_TEMPERATURE = 0.2
LAYER1_IMAGE_DETAIL = "high"
