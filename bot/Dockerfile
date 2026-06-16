FROM python:3.11-slim

WORKDIR /app

COPY bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ .
COPY shared/ ./shared/
COPY scripts/ ./scripts/
COPY alembic/ ./alembic/
COPY alembic.ini ./alembic.ini
COPY content/ ./content/

CMD ["python", "main.py"]
