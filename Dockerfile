# ===========================================
# Dockerfile для Railway - объединённый деплой
# Запускает и webapp, и bot в одном контейнере
# ===========================================

FROM python:3.11-slim

# Системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем requirements
COPY bot/requirements.txt /app/bot/requirements.txt
COPY webapp/requirements.txt /app/webapp/requirements.txt

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r /app/bot/requirements.txt \
    && pip install --no-cache-dir -r /app/webapp/requirements.txt

# Копируем код
COPY . /app/

# Копируем конфиг supervisord
RUN mkdir -p /var/log/supervisor
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Railway использует переменную PORT
ENV PORT=8080
EXPOSE 8080

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/api/health || exit 1

# Запуск через supervisord
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
