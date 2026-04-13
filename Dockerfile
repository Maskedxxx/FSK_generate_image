FROM python:3.12-slim

WORKDIR /app

# Зависимости
COPY osmi_nodes/service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код сервиса (image_service.py + alerts.py)
COPY osmi_nodes/service/ .

# Папка результатов
RUN mkdir -p results logs

# Порт
EXPOSE 8000

# Запуск
# WORKERS=1 пока tasks хранятся в памяти. Для масштабирования → Redis + WORKERS=4+
ENV WORKERS=1
CMD uvicorn image_service:app --host 0.0.0.0 --port 8000 --workers ${WORKERS}
