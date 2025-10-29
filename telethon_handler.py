import asyncio
import logging
import os
import tempfile
from pathlib import Path
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
from models import Comment, CommentStatus
from openai_handler import generate_comment, image_to_base64
from bot import send_comment_preview
from channels_config import CHANNELS

logger = logging.getLogger(__name__)

# Глобальная переменная для хранения клиента
client = None

# Путь к папке temp
TEMP_DIR = Path("temp")


def ensure_temp_dir():
    """Создает папку temp если она не существует"""
    TEMP_DIR.mkdir(exist_ok=True)
    logger.info(f"Папка temp создана/проверена: {TEMP_DIR.absolute()}")


def get_temp_file_path(suffix: str = '.jpg') -> str:
    """Возвращает путь к временному файлу в папке temp"""
    ensure_temp_dir()
    return str(TEMP_DIR / f"temp_{os.urandom(8).hex()}{suffix}")

# Словарь для хранения обработчиков событий
event_handlers = {}

# Словарь для группировки сообщений (альбомов)
message_groups = {}  # {group_id: [messages]}
# Словарь для отслеживания обработанных групп
processed_groups = set()  # {group_id}


async def process_message_group(group_id, channel_name: str, channel_config: dict):
    """
    Обрабатывает группу сообщений (альбом) как один пост
    
    Args:
        group_id: ID группы сообщений
        channel_name: Название канала
        channel_config: Конфигурация канала
    """
    if group_id not in message_groups:
        return
    
    # Проверяем, не обрабатывалась ли уже эта группа
    if group_id in processed_groups:
        logger.info(f"   ⏭️  Группа {group_id} уже обработана, пропускаем")
        return
    
    # Помечаем группу как обрабатываемую
    processed_groups.add(group_id)
    
    messages = message_groups[group_id]
    logger.info(f"🖼️  Обрабатываем группу из {len(messages)} сообщений (Group ID: {group_id})")
    
    # Собираем все данные из группы, фильтруя аудио/видео
    all_text = []
    all_photos = []
    all_photo_paths = []
    main_message_id = None
    valid_messages = []
    
    for message in messages:
        # Проверяем, не является ли сообщение только аудио/видео без текста
        is_audio_video_only = False
        if message.media and not message.text:
            if isinstance(message.media, MessageMediaDocument):
                if hasattr(message.media.document, 'mime_type'):
                    mime_type = message.media.document.mime_type
                    if mime_type.startswith('video/') or mime_type.startswith('audio/'):
                        is_audio_video_only = True
        
        if is_audio_video_only:
            logger.info(f"   ⏭️  Пропускаем сообщение {message.id} - только аудио/видео без текста")
            continue
        
        valid_messages.append(message)
        
        if message.text:
            all_text.append(message.text)
        if message.media and isinstance(message.media, MessageMediaPhoto):
            try:
                photo_path = await client.download_media(message.media, file=get_temp_file_path('.jpg'))
                if photo_path:
                    photo_base64 = image_to_base64(photo_path)
                    all_photos.append(photo_base64)
                    all_photo_paths.append(photo_path)
                    if main_message_id is None:
                        main_message_id = message.id
            except Exception as e:
                logger.error(f"Ошибка при скачивании фото из группы: {e}")
    
    if not valid_messages:
        logger.warning(f"Группа {group_id} не содержит валидных сообщений (только аудио/видео)")
        return
    
    if not all_text and not all_photos:
        logger.warning(f"Группа {group_id} не содержит текста или фото")
        return
    
    # Объединяем весь текст
    post_text = " ".join(all_text) if all_text else ""
    
    # Передаем все фото для AI
    photos_base64 = all_photos if all_photos else None
    
    logger.info(f"   📝 Объединенный текст: {post_text[:100]}...")
    logger.info(f"   📸 Фото в группе: {len(all_photos)}")
    
    # Генерируем комментарий
    try:
        # Получаем описание канала
        channel_description = None
        for channel_name_check, channel_info in CHANNELS.items():
            if channel_info["channel_id"] == channel_config["channel_id"]:
                channel_description = channel_info.get("description")
                break
        
        generated_comment = await generate_comment(post_text, photos_base64, channel_description, channel_name)
        logger.info(f"   🤖 AI сгенерировал комментарий: {generated_comment[:50]}...")
    except Exception as e:
        logger.error(f"   ❌ Ошибка при генерации комментария: {e}")
        generated_comment = "Интересный пост! 👍"
    
    # Находим chat_id для данного канала
    chat_id = None
    for channel_name_check, channel_info in CHANNELS.items():
        if channel_info["channel_id"] == channel_config["channel_id"]:
            chat_id = channel_info["chat_id"]
            break
    
    if not chat_id:
        logger.warning(f"Chat ID не найден для канала {channel_config['channel_id']}")
        return
    
    # Сохраняем в базу данных (сохраняем только первое фото для совместимости)
    comment_record = await Comment.create(
        channel_id=channel_config["channel_id"],
        message_id=main_message_id or valid_messages[0].id,
        generated_comment=generated_comment,
        post_text=post_text,
        photo_path=all_photo_paths[0] if all_photo_paths else None,
        status=CommentStatus.PENDING
    )
    
    logger.info(f"   💾 Создана запись комментария с ID {comment_record.id}, message_id={comment_record.message_id}")
    
    # Отправляем превью в бот
    logger.info(f"   📤 Отправляем уведомление в бот...")
    await send_comment_preview(
        channel_name=channel_name,
        channel_id=channel_config["channel_id"],
        message_id=main_message_id or valid_messages[0].id,
        post_text=post_text,
        comment=generated_comment,
        comment_record_id=comment_record.id,
        photo_paths=all_photo_paths  # Передаем все фото
    )
    logger.info(f"   ✅ Обработка группы сообщений завершена")
    
    # Очищаем группу
    del message_groups[group_id]


async def send_message_with_retry(event, response, max_retries=10, retry_delay=60):
    """
    Отправляет сообщение с повторными попытками при ошибках
    
    Args:
        event: Событие Telegram
        response: Текст ответа для отправки
        max_retries: Максимальное количество попыток (по умолчанию 10)
        retry_delay: Задержка между попытками в секундах (по умолчанию 60)
    
    Returns:
        bool: True если сообщение отправлено успешно, False если все попытки исчерпаны
    """
    for attempt in range(max_retries):
        try:
            await event.reply(response)
            logger.info(f"Сообщение '{response}' успешно отправлено (попытка {attempt + 1})")
            return True
            
        except FloodWaitError as e:
            wait_time = e.seconds
            logger.warning(f"FloodWaitError на попытке {attempt + 1}: нужно подождать {wait_time} секунд")
            await asyncio.sleep(wait_time)
            # После ожидания FloodWaitError пробуем еще раз без увеличения счетчика попыток
            try:
                await event.reply(response)
                logger.info(f"Сообщение '{response}' успешно отправлено после FloodWaitError")
                return True
            except Exception as retry_error:
                logger.error(f"Ошибка после FloodWaitError: {retry_error}")
                # Если ошибка после FloodWaitError, продолжаем с обычной логикой повторных попыток
                
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения (попытка {attempt + 1}/{max_retries}): {e}")
            
        # Если это не последняя попытка, ждем перед следующей
        if attempt < max_retries - 1:
            logger.info(f"Ожидание {retry_delay} секунд перед следующей попыткой...")
            await asyncio.sleep(retry_delay)
    
    logger.error(f"Не удалось отправить сообщение '{response}' после {max_retries} попыток")
    return False


async def handle_channel_message(event, channel_name: str, channel_config: dict):
    """
    Обрабатывает новое сообщение из канала
    
    Args:
        event: Событие Telegram
        channel_name: Название канала
        channel_config: Конфигурация канала
    """
    try:
        message = event.message
        sender_id = message.sender_id
        chat_id = event.chat_id
        channel_id = channel_config["channel_id"]
        
        logger.info(f"🔍 Проверяем сообщение: sender_id={sender_id}, chat_id={chat_id}, channel_id={channel_id}")
        
        if sender_id != channel_id:
            logger.info(f"   ⏭️  Пропускаем - сообщение не от целевого канала (sender_id={sender_id}, chat_id={chat_id})")
            return
        logger.info(f"   ✅ Сообщение от канала (sender_id={sender_id}, chat_id={chat_id})")
        
        # Детальное логирование типа сообщения
        logger.info(f"📨 Получено сообщение от канала {channel_name} (ID: {channel_id})")
        logger.info(f"   Message ID: {message.id}")
        logger.info(f"   Дата: {message.date}")
        logger.info(f"   Тип медиа: {type(message.media).__name__ if message.media else 'None'}")
        logger.info(f"   Есть текст: {'Да' if message.text else 'Нет'}")
        logger.info(f"   Текст: {message.text[:100] if message.text else 'Нет текста'}...")
        
        # Проверяем, является ли это частью группы сообщений (альбом)
        if hasattr(message, 'grouped_id') and message.grouped_id:
            group_id = message.grouped_id
            
            # Проверяем, не обрабатывалась ли уже эта группа
            if group_id in processed_groups:
                logger.info(f"   ⏭️  Группа {group_id} уже обработана, пропускаем")
                return
            
            logger.info(f"   🖼️  ГРУППА СООБЩЕНИЙ! Group ID: {group_id}")
            
            # Добавляем сообщение в группу
            if group_id not in message_groups:
                message_groups[group_id] = []
            
            message_groups[group_id].append(message)
            logger.info(f"   📥 Добавлено в группу. Всего в группе: {len(message_groups[group_id])}")
            
            # Ждем немного, чтобы собрать все сообщения группы
            await asyncio.sleep(3)  # Увеличиваем время ожидания
            
            # Проверяем, все ли сообщения группы собраны
            # Обрабатываем группу только если это последнее сообщение в группе
            # или если прошло достаточно времени
            if len(message_groups[group_id]) >= 2:  # Ожидаем минимум 2 сообщения для альбома
                logger.info(f"   ✅ Группа собрана, обрабатываем...")
                await process_message_group(group_id, channel_name, channel_config)
            else:
                logger.info(f"   ⏳ Ждем остальные сообщения группы...")
            
            return
        
        # Обычное сообщение (не группа)
        logger.info(f"   📝 Обычное сообщение (не группа)")
        
        # Извлекаем текст поста
        post_text = message.text or ""
        
        # Проверяем, является ли сообщение только аудио/видео без текста
        if message.media and not post_text:
            if isinstance(message.media, MessageMediaDocument):
                if hasattr(message.media.document, 'mime_type'):
                    mime_type = message.media.document.mime_type
                    if mime_type.startswith('video/'):
                        logger.info(f"   🎥 Пропускаем сообщение - только видео без текста")
                        return
                    elif mime_type.startswith('audio/'):
                        logger.info(f"   🎵 Пропускаем сообщение - только аудио без текста")
                        return
        
        # Обрабатываем медиа, если есть
        photo_path = None
        photo_base64 = None
        
        if message.media:
            if isinstance(message.media, MessageMediaPhoto):
                logger.info(f"   📸 Обрабатываем фото...")
                try:
                    # Скачиваем фото в папку temp
                    photo_path = await client.download_media(message.media, file=get_temp_file_path('.jpg'))
                    if photo_path:
                        photo_base64 = image_to_base64(photo_path)
                        logger.info(f"   ✅ Фото скачано и конвертировано в base64")
                    else:
                        logger.warning(f"   ❌ Не удалось скачать фото")
                except Exception as e:
                    logger.error(f"   ❌ Ошибка при скачивании фото: {e}")
            elif isinstance(message.media, MessageMediaDocument):
                # Проверяем, является ли документ видео или аудио
                if hasattr(message.media.document, 'mime_type'):
                    mime_type = message.media.document.mime_type
                    if mime_type.startswith('video/'):
                        logger.info(f"   🎥 Пропускаем видео (MIME: {mime_type})")
                    elif mime_type.startswith('audio/'):
                        logger.info(f"   🎵 Пропускаем аудио (MIME: {mime_type})")
                    else:
                        logger.info(f"   📄 Документ (MIME: {mime_type}) - пропускаем")
                else:
                    logger.info(f"   📄 Документ без MIME типа - пропускаем")
            else:
                logger.info(f"   📎 Другой тип медиа: {type(message.media).__name__} - пропускаем")
        else:
            logger.info(f"   📝 Сообщение без медиа")
        
        # Генерируем комментарий
        try:
            # Получаем описание канала
            channel_description = None
            for channel_name_check, channel_info in CHANNELS.items():
                if channel_info["channel_id"] == channel_id:
                    channel_description = channel_info.get("description")
                    break
            
            # Передаем фото как список (даже если одно)
            photos_base64 = [photo_base64] if photo_base64 else None
            generated_comment = await generate_comment(post_text, photos_base64, channel_description, channel_name)
            logger.info(f"   🤖 AI сгенерировал комментарий: {generated_comment[:50]}...")
        except Exception as e:
            logger.error(f"   ❌ Ошибка при генерации комментария: {e}")
            generated_comment = "Интересный пост! 👍"
        
        # Находим chat_id для данного канала
        chat_id = None
        for channel_name, channel_info in CHANNELS.items():
            if channel_info["channel_id"] == channel_id:
                chat_id = channel_info["chat_id"]
                break
        
        if not chat_id:
            logger.warning(f"Chat ID не найден для канала {channel_id}")
            return
        
        # Сохраняем в базу данных
        logger.info(f"Сохраняем запись: channel_id={channel_id}, message_id={message.id}")
        
        comment_record = await Comment.create(
            channel_id=channel_id,
            message_id=message.id,
            generated_comment=generated_comment,
            post_text=post_text,
            photo_path=photo_path,
            status=CommentStatus.PENDING
        )
        
        logger.info(f"   💾 Создана запись комментария с ID {comment_record.id}, message_id={comment_record.message_id}")
        
        # Отправляем превью в бот
        logger.info(f"   📤 Отправляем уведомление в бот...")
        await send_comment_preview(
            channel_name=channel_name,
            channel_id=channel_id,
            message_id=message.id,
            post_text=post_text,
            comment=generated_comment,
            comment_record_id=comment_record.id,
            photo_path=photo_path,
            photo_paths=[photo_path] if photo_path else None
        )
        logger.info(f"   ✅ Обработка сообщения завершена")
        
    except FloodWaitError as e:
        wait_time = e.seconds
        logger.warning(f"FloodWaitError в обработчике: нужно подождать {wait_time} секунд")
        await asyncio.sleep(wait_time)
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}")




async def send_comment_to_post(comment_record) -> bool:
    """
    Отправляет комментарий к посту в чате
    
    Args:
        comment_record: Запись комментария из БД
    
    Returns:
        bool: True если комментарий отправлен успешно
    """
    channel_id = comment_record.channel_id
    message_id = comment_record.message_id
    comment = comment_record.generated_comment
    
    try:
        if not client:
            logger.error("Telethon клиент не инициализирован")
            return False
        
        # Находим chat_id для данного канала
        chat_id = None
        for channel_name, channel_info in CHANNELS.items():
            if channel_info["channel_id"] == channel_id:
                chat_id = channel_info["chat_id"]
                break
        
        if not chat_id:
            logger.error(f"Chat ID не найден для канала {channel_id}")
            return False
        
        # Получаем сообщение по ID в чате
        message = await client.get_messages(chat_id, ids=message_id)
        if not message:
            logger.error(f"Сообщение {message_id} не найдено в чате {chat_id}")
            return False
        
        # Отправляем комментарий как ответ на сообщение
        sent_message = None
        try:
            sent_message = await message.reply(comment)
            success = True
        except FloodWaitError as e:
            wait_time = e.seconds
            logger.warning(f"FloodWaitError при отправке комментария: нужно подождать {wait_time} секунд")
            await asyncio.sleep(wait_time)
            try:
                sent_message = await message.reply(comment)
                success = True
            except Exception as retry_error:
                logger.error(f"Ошибка после FloodWaitError: {retry_error}")
                success = False
        except Exception as e:
            logger.error(f"Ошибка при отправке комментария: {e}")
            success = False
        
        # Сохраняем ID отправленного комментария в записи
        if success and sent_message:
            comment_record.sent_message_id = sent_message.id
            await comment_record.save()
            logger.info(f"Комментарий отправлен с ID: {sent_message.id}")
        
        return success
        
    except Exception as e:
        logger.error(f"Ошибка при отправке комментария: {e}")
        return False


async def setup_channel_handlers(telethon_client: TelegramClient):
    """
    Настраивает обработчики для всех каналов из конфигурации
    
    Args:
        telethon_client: Клиент Telethon
    """
    global client
    client = telethon_client
    
    for channel_name, channel_config in CHANNELS.items():
        try:
            chat_id = channel_config["chat_id"]
            
            # Создаем обработчик для конкретного канала
            handler = lambda event, name=channel_name, config=channel_config: handle_channel_message(event, name, config)
            
            # Добавляем обработчик событий
            telethon_client.add_event_handler(handler, events.NewMessage(chats=chat_id))
            event_handlers[channel_name] = handler
            
            logger.info(f"Обработчик добавлен для канала '{channel_name}' (чат ID: {chat_id})")
            
        except Exception as e:
            logger.error(f"Ошибка при настройке обработчика для канала '{channel_name}': {e}")


async def cleanup_temp_files():
    """Очищает временные файлы с фотографиями"""
    try:
        # Очищаем все файлы из папки temp
        if TEMP_DIR.exists():
            for file_path in TEMP_DIR.iterdir():
                if file_path.is_file():
                    try:
                        file_path.unlink()
                        logger.info(f"Удален временный файл: {file_path}")
                    except Exception as e:
                        logger.error(f"Ошибка при удалении файла {file_path}: {e}")
        
        # Также очищаем файлы из базы данных (для совместимости)
        for channel_name, channel_config in CHANNELS.items():
            # Получаем все записи с фото
            comments_with_photos = await Comment.filter(
                channel_id=channel_config["channel_id"],
                photo_path__isnull=False
            ).all()
            
            for comment in comments_with_photos:
                if comment.photo_path and os.path.exists(comment.photo_path):
                    try:
                        os.remove(comment.photo_path)
                        logger.info(f"Удален файл из БД: {comment.photo_path}")
                    except Exception as e:
                        logger.error(f"Ошибка при удалении файла {comment.photo_path}: {e}")
                        
    except Exception as e:
        logger.error(f"Ошибка при очистке временных файлов: {e}")
