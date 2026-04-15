# Гайд по управлению сервером AIKAI

## 1. Подключение по SSH

SSH-ключ уже настроен (`~/.ssh/id_ed25519`). Подключение:

```bash
ssh root@161.35.153.41
```

Проект на сервере: `/root/AIBOTIK/`

---

## 2. Обновление кода на сервере

### Полный цикл (локально → сервер)

```bash
# 1. Локально: коммит и пуш
git add .
git commit -m "описание изменений"
git push origin main

# 2. Локально: мерж в production
git checkout production
git merge main --no-edit
git push origin production
git checkout main

# 3. На сервере: подтянуть код и пересобрать
ssh root@161.35.153.41
cd /root/AIBOTIK
git stash                    # сохранить локальные изменения на сервере
git pull origin production   # подтянуть новый код
git stash pop                # вернуть локальные изменения
docker compose up -d --build # пересобрать и перезапустить
```

### Одной командой с локальной машины

```bash
ssh root@161.35.153.41 "cd /root/AIBOTIK && git stash && git pull origin production && git stash pop && docker compose up -d --build"
```

### Пересобрать только один сервис (быстрее)

```bash
# Только бот
ssh root@161.35.153.41 "cd /root/AIBOTIK && git stash && git pull origin production && git stash pop && docker compose up -d --build bot"

# Только бэкенд
ssh root@161.35.153.41 "cd /root/AIBOTIK && git stash && git pull origin production && git stash pop && docker compose up -d --build backend"

# Только фронтенд
ssh root@161.35.153.41 "cd /root/AIBOTIK && git stash && git pull origin production && git stash pop && docker compose up -d --build frontend"
```

---

## 3. Управление контейнерами

### Подключиться и перейти в папку

```bash
ssh root@161.35.153.41
cd /root/AIBOTIK
```

### Список контейнеров

```bash
docker ps                          # запущенные
docker ps -a                       # все (включая остановленные)
docker compose ps                  # только контейнеры проекта
```

### Перезапуск

```bash
docker compose restart             # перезапустить все
docker compose restart bot         # перезапустить только бота
docker compose restart backend     # перезапустить только бэкенд
docker compose restart worker      # перезапустить только воркер
```

### Остановка и запуск

```bash
docker compose stop                # остановить все
docker compose start               # запустить все
docker compose down                # остановить и удалить контейнеры
docker compose up -d               # запустить (без пересборки)
docker compose up -d --build       # пересобрать и запустить
```

---

## 4. Логи

```bash
# Логи конкретного сервиса
docker logs aibotik-bot-1          # бот
docker logs aibotik-backend-1      # бэкенд (FastAPI)
docker logs aibotik-worker-1       # воркер (генерация картинок)
docker logs aibotik-postgres-1     # база данных
docker logs aibotik-nginx-1        # nginx
docker logs aibotik-seed-1         # сид (промпты/контент)

# Последние N строк
docker logs aibotik-bot-1 --tail 50

# Следить в реальном времени
docker logs aibotik-bot-1 -f

# Через docker compose (удобнее)
docker compose logs bot -f --tail 50
docker compose logs backend -f --tail 50
```

---

## 5. База данных (PostgreSQL)

### Подключение к БД

```bash
docker exec -it aibotik-postgres-1 psql -U rpbot -d rpbot
```

### Полезные SQL-команды

```sql
-- Список таблиц
\dt

-- Посмотреть промпты
SELECT key, category, name, LENGTH(content) FROM prompts ORDER BY category, key;

-- Посмотреть содержимое промпта
SELECT content FROM prompts WHERE key = 'common_style_guide';

-- Посмотреть пользователей
SELECT telegram_id, username, subscription_plan, created_at FROM users ORDER BY created_at DESC LIMIT 20;

-- Посмотреть персонажей
SELECT id, name, is_nsfw, created_by_username FROM characters;

-- Выход
\q
```

### Выполнить SQL одной командой (без входа в psql)

```bash
docker exec aibotik-postgres-1 psql -U rpbot -d rpbot -c "SELECT COUNT(*) FROM users;"
```

---

## 6. Редактирование .env на сервере

```bash
# Просмотреть
ssh root@161.35.153.41 "cat /root/AIBOTIK/.env"

# Отредактировать (через nano)
ssh root@161.35.153.41
nano /root/AIBOTIK/.env
# Ctrl+O — сохранить, Ctrl+X — выйти

# Или заменить конкретное значение одной командой
ssh root@161.35.153.41 "sed -i 's|BOT_TOKEN=.*|BOT_TOKEN=новый_токен|' /root/AIBOTIK/.env"
```

После изменения `.env` нужно перезапустить контейнеры:

```bash
docker compose up -d  # (или docker compose restart)
```

---

## 7. Redis (кэш)

```bash
# Подключиться к Redis
docker exec -it aibotik-redis-1 redis-cli

# Посмотреть все ключи (осторожно, может быть много)
KEYS *

# Очистить весь кэш
FLUSHALL

# Выход
EXIT
```

---

## 8. Структура сервисов

| Сервис     | Контейнер              | Что делает                           |
|------------|------------------------|--------------------------------------|
| nginx      | aibotik-nginx-1        | Проксирует запросы, SSL, статика     |
| postgres   | aibotik-postgres-1     | База данных                          |
| redis      | aibotik-redis-1        | Кэш промптов, задачи генерации      |
| backend    | aibotik-backend-1      | FastAPI: API, чат, админка           |
| frontend   | aibotik-frontend-1     | Vue.js: веб-интерфейс               |
| worker     | aibotik-worker-1       | ARQ: генерация картинок в фоне      |
| bot        | aibotik-bot-1          | Telegram бот (aiogram)               |
| seed       | aibotik-seed-1         | Инициализация промптов и контента    |

---

## 9. Частые проблемы

### Бот не отвечает

```bash
docker logs aibotik-bot-1 --tail 20    # посмотреть ошибки
docker compose restart bot             # перезапустить
```

### Сайт не открывается

```bash
docker logs aibotik-nginx-1 --tail 20
docker compose restart nginx
```

### Картинки не генерируются

```bash
docker logs aibotik-worker-1 --tail 20
docker compose restart worker
```

### Всё сломалось — полный перезапуск

```bash
cd /root/AIBOTIK
docker compose down
docker compose up -d --build
```

### Закончилось место на диске

```bash
df -h                                  # проверить место
docker system prune -a                 # удалить неиспользуемые образы (освободит место)
```
