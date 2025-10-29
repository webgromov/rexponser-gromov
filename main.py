import asyncio
import logging
import signal
import sys
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from tortoise import Tortoise
from config import API_ID, API_HASH, PHONE_NUMBER, DATABASE_URL
from models import Comment
from telethon_handler import setup_channel_handlers, cleanup_temp_files, send_comment_to_post, ensure_temp_dir
from bot import start_bot, stop_bot, set_send_comment_function

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Глобальная переменная для контроля работы
_running = True

# Инициализация Telethon клиента
client = TelegramClient('tgsession', API_ID, API_HASH)


def handle_exception(loop, context):
    """Глобальный обработчик ошибок для asyncio"""
    exception = context.get('exception')
    if isinstance(exception, FloodWaitError):
        wait_time = exception.seconds
        logger.warning(f"Глобальный FloodWaitError: нужно подождать {wait_time} секунд")
    else:
        logger.error(f"Необработанное исключение: {exception}")


def signal_handler(signum, frame):
    """Обработчик сигналов остановки"""
    global _running
    logger.info(f"Получен сигнал {signum}, завершение работы...")
    _running = False


async def init_database():
    """Инициализация базы данных"""
    try:
        await Tortoise.init(
            db_url=DATABASE_URL,
            modules={'models': ['models']}
        )
        await Tortoise.generate_schemas()
        logger.info("База данных инициализирована")
    except Exception as e:
        logger.error(f"Ошибка при инициализации базы данных: {e}")
        raise


async def close_database():
    """Закрытие соединения с базой данных"""
    try:
        await Tortoise.close_connections()
        logger.info("Соединение с базой данных закрыто")
    except Exception as e:
        logger.error(f"Ошибка при закрытии базы данных: {e}")


async def main():
    """Основная функция"""
    global _running
    logger.info("Запуск Telegram монитора и бота...")
    
    # Устанавливаем обработчики сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Проверяем конфигурацию
    if not API_ID or not API_HASH:
        logger.error("API_ID или API_HASH не заданы. Проверьте переменные окружения")
        return
    
    if not PHONE_NUMBER:
        logger.error("PHONE_NUMBER не задан. Проверьте переменную окружения PHONE_NUMBER")
        return
    
    # Устанавливаем глобальный обработчик исключений
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(handle_exception)
    
    try:
        # Инициализация базы данных
        await init_database()
        
        # Создаем папку temp для медиа файлов
        ensure_temp_dir()
        
        # Устанавливаем функцию отправки комментариев в боте
        set_send_comment_function(send_comment_to_post)
        
        # Запуск Telethon клиента
        await client.start(phone=PHONE_NUMBER)
        logger.info(f"Telethon клиент запущен с номером {PHONE_NUMBER}")
        
        me = await client.get_me()
        logger.info(f"Авторизован как: {me.first_name} (@{me.username})")
        
        # Запуск aiogram бота
        bot_task = asyncio.create_task(start_bot())
        logger.info("Бот запущен")
        
        # Небольшая задержка для инициализации бота
        await asyncio.sleep(2)
        
        # Настройка обработчиков каналов
        await setup_channel_handlers(client)
        logger.info("Мониторинг сообщений запущен")
        
        logger.info("Все сервисы запущены. Нажмите Ctrl+C для остановки.")
        
        # Ожидаем завершения бота или сигнала остановки
        try:
            while _running and not bot_task.done():
                await asyncio.sleep(0.1)
        except KeyboardInterrupt:
            logger.info("Получен сигнал остановки...")
        except Exception as e:
            logger.error(f"Ошибка в работе: {e}")
            
    except Exception as e:
        logger.error(f"Критическая ошибка в main: {e}")
    finally:
        # Останавливаем все сервисы
        logger.info("Остановка всех сервисов...")
        
        try:
            # Останавливаем бота
            await stop_bot()
        except Exception as e:
            logger.error(f"Ошибка при остановке бота: {e}")
        
        try:
            # Останавливаем Telethon клиент
            await client.disconnect()
            logger.info("Telethon клиент отключен")
        except Exception as e:
            logger.error(f"Ошибка при отключении Telethon: {e}")
        
        try:
            # Очищаем временные файлы
            await cleanup_temp_files()
        except Exception as e:
            logger.error(f"Ошибка при очистке временных файлов: {e}")
        
        try:
            # Закрываем базу данных
            await close_database()
        except Exception as e:
            logger.error(f"Ошибка при закрытии базы данных: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Программа остановлена пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        logger.info("Программа завершена")
