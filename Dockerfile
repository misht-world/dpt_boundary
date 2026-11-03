# Схемы границ территорий — образ для pi5 (arm64)
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data

# Шрифты для подписей на карте: Liberation Serif — бесплатный аналог
# Times New Roman с кириллицей (Times на Linux недоступен).
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# Зависимости отдельным слоём: pyproj и pillow ставятся готовыми
# колёсами для arm64, компиляции на Pi не требуется.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

VOLUME ["/data"]
EXPOSE 8077

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8077", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
