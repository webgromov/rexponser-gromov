import logging
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from models import Comment, CommentStatus
from config import BOT_TOKEN, ADMIN_USER_ID
from channels_config import CHANNELS
# Импорт send_comment_to_post убран для избежания циклического импорта

logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Глобальная переменная для контроля работы бота
_bot_running = True

# Глобальная переменная для функции отправки комментариев
_send_comment_func = None


def set_send_comment_function(func):
    """Устанавливает функцию для отправки комментариев"""
    global _send_comment_func
    _send_comment_func = func


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    if message.from_user.id != ADMIN_USER_ID:
        await message.answer("❌ У вас нет доступа к этому боту.")
        return
    
    text = "🤖 Бот для мониторинга каналов\n\nБот активен и отслеживает посты в настроенных каналах. Уведомления о новых постах будут приходить автоматически."
    await message.answer(text)


@dp.callback_query(F.data.startswith("send:"))
async def send_comment_handler(callback: CallbackQuery):
    """Обработчик отправки комментария"""
    if callback.from_user.id != ADMIN_USER_ID:
        await callback.answer("❌ У вас нет доступа к этому боту.")
        return
    
    try:
        # Извлекаем comment_record_id из callback_data
        _, comment_record_id_str = callback.data.split(":")
        comment_record_id = int(comment_record_id_str)
        
        logger.info(f"Ищем комментарий по ID записи: {comment_record_id}")
        
        # Получаем комментарий из БД по ID записи
        logger.info(f"Ищем запись с ID {comment_record_id} и статусом PENDING")
        comment_record = await Comment.filter(
            id=comment_record_id,
            status=CommentStatus.PENDING
        ).first()
        
        # Если не найден PENDING, проверим запись с этим ID
        if not comment_record:
            logger.info(f"PENDING запись не найдена, ищем любую запись с ID {comment_record_id}")
            comment_record = await Comment.filter(id=comment_record_id).first()
            
            if comment_record:
                logger.info(f"Запись найдена, но статус: {comment_record.status}")
                logger.info(f"Детали записи: channel_id={comment_record.channel_id}, message_id={comment_record.message_id}")
            else:
                logger.error(f"Запись с ID {comment_record_id} не найдена в БД!")
            
            await callback.answer("❌ Комментарий не найден или уже отправлен")
            return
        
        logger.info(f"✅ Найдена PENDING запись: ID={comment_record.id}, channel_id={comment_record.channel_id}, message_id={comment_record.message_id}")
        
        # Отправляем комментарий через Telethon
        if not _send_comment_func:
            await callback.answer("❌ Функция отправки комментариев не инициализирована")
            return
            
        success = await _send_comment_func(comment_record)
        
        if success:
            # Обновляем статус в БД
            comment_record.status = CommentStatus.SENT
            await comment_record.save()
            
            # Создаем ссылку на комментарий
            # Формат: https://t.me/c/{chat_id}/{sent_message_id}
            chat_id = None
            for channel_name, channel_info in CHANNELS.items():
                if channel_info["channel_id"] == comment_record.channel_id:
                    chat_id = channel_info["chat_id"]
                    break
            
            if chat_id and comment_record.sent_message_id:
                # Убираем знак минус и добавляем 1000000000000 для каналов
                if chat_id < 0:
                    chat_id_str = str(chat_id)[4:]  # Убираем -100
                else:
                    chat_id_str = str(chat_id)
                
                comment_url = f"https://t.me/c/{chat_id_str}/{comment_record.sent_message_id}"
                
                # Создаем кнопку "Посмотреть комментарий"
                markup = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="👀 Посмотреть комментарий", 
                        url=comment_url
                    )]
                ])
                
                # Редактируем сообщение с кнопкой
                await callback.message.edit_reply_markup(reply_markup=markup)
                await callback.answer("✅ Комментарий успешно отправлен!")
            else:
                await callback.answer("✅ Комментарий отправлен, но ссылка недоступна")
        else:
            # Обновляем статус на failed
            comment_record.status = CommentStatus.FAILED
            await comment_record.save()
            
            await callback.answer("❌ Не удалось отправить комментарий")
            
    except Exception as e:
        logger.error(f"Ошибка при отправке комментария: {e}")
        await callback.answer("❌ Произошла ошибка при отправке комментария")


async def send_comment_preview(channel_name: str, channel_id: int, message_id: int, 
                             post_text: str, comment: str, comment_record_id: int, 
                             photo_path: str = None, photo_paths: list = None):
    """
    Отправляет превью комментария администратору
    
    Args:
        channel_name: Название канала
        channel_id: ID канала
        message_id: ID сообщения
        post_text: Текст поста
        comment: Сгенерированный комментарий
        comment_record_id: ID записи в БД
        photo_path: Путь к одному фото (для обратной совместимости)
        photo_paths: Список путей к фото (для медиа-групп)
    """
    logger.info(f"Отправляем превью комментария для канала {channel_name} (ID: {channel_id})")
    try:
        # Формируем текст сообщения
        text = f"📢 <b>Новый пост в канале: {channel_name}</b>\n\n"
        text += f"<b>Текст:</b> {post_text[:500]}{'...' if len(post_text) > 500 else ''}\n\n"
        text += f"<b>Комментарий:</b> {comment}"
        
        # Создаем кнопку для отправки комментария
        callback_data = f"send:{comment_record_id}"
        logger.info(f"Создаем кнопку с callback_data: {callback_data}")
        
        # Создаем ссылку на пост
        # Формат: https://t.me/c/{chat_id}/{message_id}
        chat_id = None
        for channel_name_check, channel_info in CHANNELS.items():
            if channel_info["channel_id"] == channel_id:
                chat_id = channel_info["chat_id"]
                break
        
        post_url = None
        if chat_id:
            # Убираем знак минус и добавляем 1000000000000 для каналов
            if chat_id < 0:
                chat_id_str = str(chat_id)[4:]  # Убираем -100
            else:
                chat_id_str = str(chat_id)
            
            post_url = f"https://t.me/c/{chat_id_str}/{message_id}"
        
        # Создаем кнопки в ряд
        buttons = []
        row_buttons = []
        
        # Добавляем кнопку "Смотреть пост" если есть ссылка
        if post_url:
            row_buttons.append(InlineKeyboardButton(
                text="👀 Смотреть", 
                url=post_url
            ))
        
        # Добавляем кнопку комментария
        row_buttons.append(InlineKeyboardButton(
            text="🔴 Прокомментировать", 
            callback_data=callback_data
        ))
        
        # Если есть кнопки, добавляем их в ряд
        if row_buttons:
            buttons.append(row_buttons)
        
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        # Отправляем сообщение с фото или без
        if photo_paths and len(photo_paths) > 1:
            # Отправляем всю медиа-группу
            from aiogram.types import FSInputFile, InputMediaPhoto
            media_group = []
            for i, path in enumerate(photo_paths):
                photo_file = FSInputFile(path)
                if i == 0:
                    # Первое фото с подписью
                    media_group.append(InputMediaPhoto(media=photo_file, caption=text, parse_mode="HTML"))
                else:
                    # Остальные фото без подписи
                    media_group.append(InputMediaPhoto(media=photo_file))
            
            await bot.send_media_group(
                chat_id=ADMIN_USER_ID,
                media=media_group
            )
            
            # Отправляем кнопки сразу после медиа-группы
            await bot.send_message(
                chat_id=ADMIN_USER_ID,
                text="Выберите действие:",
                reply_markup=markup,
                parse_mode="HTML"
            )
        elif photo_path or (photo_paths and len(photo_paths) == 1):
            # Отправляем одно фото
            from aiogram.types import FSInputFile
            single_photo_path = photo_path or photo_paths[0]
            photo_file = FSInputFile(single_photo_path)
            await bot.send_photo(
                chat_id=ADMIN_USER_ID,
                photo=photo_file,
                caption=text,
                reply_markup=markup,
                parse_mode="HTML"
            )
        else:
            # Отправляем только текст
            await bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=text,
                reply_markup=markup,
                parse_mode="HTML"
            )
            
        logger.info(f"✅ Успешно отправлено превью комментария для канала {channel_name}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке превью комментария: {e}")
        import traceback
        logger.error(f"Детали ошибки: {traceback.format_exc()}")


async def start_bot():
    """Запуск бота"""
    global _bot_running
    logger.info("Запуск Telegram бота...")
    
    try:
        # Запускаем polling
        await dp.start_polling(bot, stop_signals=None)
    except asyncio.CancelledError:
        logger.info("Бот получил сигнал остановки")
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        _bot_running = False
        await bot.session.close()
        logger.info("Бот остановлен")


async def stop_bot():
    """Остановка бота"""
    global _bot_running
    _bot_running = False
    logger.info("Остановка бота...")
    
    try:
        # Останавливаем polling
        await dp.stop_polling()
    except Exception as e:
        logger.error(f"Ошибка при остановке polling: {e}")
    
    try:
        # Закрываем сессию
        await bot.session.close()
    except Exception as e:
        logger.error(f"Ошибка при закрытии сессии: {e}")


