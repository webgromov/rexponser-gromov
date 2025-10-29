# Telegram Channel Comment Bot

Система автоматического мониторинга постов в Telegram каналах с генерацией комментариев через ChatGPT и их отправкой в бот для подтверждения перед публикацией.

> **Примечание**: Проект использует [uv](https://github.com/astral-sh/uv) для управления зависимостями Python.

## Архитектура

Система состоит из трех основных компонентов:
1. **Telethon клиент** - мониторит указанные каналы и отправляет посты на обработку
2. **OpenAI обработчик** - анализирует посты (текст + фото) и генерирует комментарии
3. **Aiogram бот** - отправляет уведомления пользователю с кнопкой для публикации комментария

## Установка

1. Установите uv (если еще не установлен):
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Или через pip
pip install uv
```

2. Клонируйте репозиторий:
```bash
git clone <repository-url>
cd rexponser_gromov
```

3. Установите зависимости:
```bash
uv sync
```

4. Создайте файл `.env` на основе `.env.example`:
```bash
cp .env.example .env
```

5. Заполните переменные окружения в `.env`:
```env
# Telegram API (Telethon)
API_ID=your_api_id
API_HASH=your_api_hash
PHONE_NUMBER=+1234567890

# OpenAI API
OPENAI_API_KEY=your_openai_api_key
# Прокси для OpenAI (SOCKS5)
# PROXY_URL=socks5://username:password@proxy_host:port

# Telegram Bot (Aiogram)
BOT_TOKEN=your_bot_token
ADMIN_USER_ID=your_telegram_user_id

# PostgreSQL Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=telegram_bot
DB_USER=postgres
DB_PASSWORD=your_password
```

6. Настройте каналы в `channels_config.py`:
```python
CHANNELS = {
    "Название канала": {
        "channel_id": -1001234567890,  # ID канала
        "chat_id": -1001234567890      # ID чата
    }
}
```

7. Запустите PostgreSQL через Docker Compose:
```bash
docker-compose up -d postgres
```

> **Примечание**: Docker Compose автоматически использует переменные `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_PORT` из вашего `.env` файла. Если переменные не заданы, используются значения по умолчанию.

Или создайте базу данных PostgreSQL вручную:
```sql
CREATE DATABASE telegram_bot;
```

## Запуск

### С Docker (рекомендуется)

1. Запустите PostgreSQL:
```bash
docker-compose up -d postgres
```

2. Запустите приложение:
```bash
uv run python main.py
```

### Без Docker

```bash
uv run python main.py
```

## Использование

1. Запустите бота командой `/start` в Telegram
2. При появлении новых постов в отслеживаемых каналах:
   - Система автоматически сгенерирует комментарий через ChatGPT
   - Вам придет уведомление с превью поста и сгенерированным комментарием
   - Нажмите "Оставить комментарий" для публикации комментария в канале

## Структура проекта

```
├── .env                      # API ключи и конфиги
├── .env.example             # Пример конфигурации
├── config.py                # Загрузка конфигурации из .env
├── channels_config.py       # Словарь отслеживаемых каналов
├── main.py                  # Точка входа, запуск всех сервисов
├── pyproject.toml          # Конфигурация проекта и зависимости
├── docker-compose.yml      # Docker Compose для PostgreSQL
├── init.sql                # SQL скрипт инициализации БД
├── models.py               # Tortoise ORM модели для PostgreSQL
├── telethon_handler.py     # Мониторинг каналов через Telethon
├── openai_handler.py       # Генерация комментариев через ChatGPT
├── bot.py                  # Aiogram бот с обработчиками
└── README.md               # Инструкция по запуску
```

## Получение API ключей

### Telegram API
1. Перейдите на https://my.telegram.org/
2. Войдите в аккаунт
3. Перейдите в "API development tools"
4. Создайте новое приложение и получите `API_ID` и `API_HASH`

### OpenAI API
1. Перейдите на https://platform.openai.com/
2. Создайте аккаунт или войдите
3. Перейдите в "API Keys"
4. Создайте новый ключ API

### Telegram Bot Token
1. Найдите @BotFather в Telegram
2. Отправьте команду `/newbot`
3. Следуйте инструкциям для создания бота
4. Получите токен бота

## Логирование

Все операции логируются в консоль с указанием времени, уровня и сообщения. Логи включают:
- Запуск и остановку сервисов
- Обработку сообщений из каналов
- Генерацию комментариев
- Отправку уведомлений
- Ошибки и предупреждения

## Обработка ошибок

Система включает обработку:
- `FloodWaitError` - автоматические повторы с ожиданием
- Ошибки сети и API
- Ошибки базы данных
- Graceful shutdown при получении сигналов остановки

## Docker команды

- `docker-compose up -d postgres` - запуск PostgreSQL
- `docker-compose down` - остановка PostgreSQL
- `docker-compose logs postgres` - просмотр логов PostgreSQL
- `docker-compose exec postgres psql -U ${DB_USER:-postgres} -d ${DB_NAME:-telegram_bot}` - подключение к БД

**Переменные окружения для Docker:**
- `DB_NAME` - название базы данных (по умолчанию: `telegram_bot`)
- `DB_USER` - пользователь PostgreSQL (по умолчанию: `postgres`)
- `DB_PASSWORD` - пароль PostgreSQL (по умолчанию: `postgres`)
- `DB_PORT` - порт PostgreSQL (по умолчанию: `5432`)

## Требования

- Python 3.8+
- PostgreSQL 12+ (или Docker)
- Telegram аккаунт с доступом к каналам
- OpenAI API ключ
- Docker (опционально, для PostgreSQL)
