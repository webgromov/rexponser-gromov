import openai
import base64
import logging
import httpx
from config import OPENAI_API_KEY, PROXY_URL

logger = logging.getLogger(__name__)

# Настройка OpenAI клиента
client = openai.AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    http_client=httpx.AsyncClient(proxy=PROXY_URL)
)


async def generate_comment(text: str, photos_base64: list = None, channel_description: str = None, channel_name: str = None) -> str:
    """
    Генерирует комментарий к посту с помощью OpenAI
    
    Args:
        text: Текст поста
        photos_base64: Список фото в формате base64 (опционально)
        channel_description: Описание канала для контекста
    
    Returns:
        str: Сгенерированный комментарий
    """
    logger.info(f"Начинаем генерацию комментария для текста: {text[:100]}...")
    try:
        # Промпт для генерации комментария
        channel_context = f"\nО канале: {channel_description}" if channel_description else ""
        
        system_prompt = f"""Ты умный и живой человек, который комментирует посты в Telegram канале. Твоя задача - писать короткие, яркие и человеческие комментарии.

{channel_context}

Ты пишешь комментарий от имени Алекса Громова. Алекс Громов - it-предприниматель, разрабатывает AI-агентов.
У него агентство продуктовой IT-разработки и он программист. Ему 22 года. Выражайся как настоящий человек, а не как бот.

ПРАВИЛА КОММЕНТАРИЕВ:
- Длина: 2-6 слов максимум
- Стиль: живой, эмоциональный, как настоящий человек
- Используй emoji, но не всегда: 😁⚡️🔥😂💪🎯🚀💡👍👏
- Показывай эмоции и реакцию
- Будь конкретным и по делу
- Избегай формальности и "ботности"

ПРИМЕРЫ ХОРОШИХ КОММЕНТАРИЕВ:
- "Точно! 🔥"
- "Крутая схема ⚡️"
- "Попробую 😁"
- "Где детали? 💡"
- "Мощно! 💪"
- "А как с...? 🤔"
- "Бомба! 🚀"
- "Согласен 👍"

Если в посте есть медиа-группа (несколько фото/схем/диаграмм), анализируй всю группу целиком и реагируй на общий контент эмоционально и по делу."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Текст поста: {text}. Напиши короткий живой комментарий к этому посту:\n\n{text}"}
        ]

        # Если есть фото, добавляем их в сообщение
        if photos_base64:
            content = [{"type": "text", "text": f"Напиши короткий живой комментарий к этому посту:\n\n{text}"}]
            
            # Добавляем все фото из медиа-группы
            for i, photo_base64 in enumerate(photos_base64):
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{photo_base64}"
                    }
                })
            
            messages[1]["content"] = content

        # Выбираем модель в зависимости от наличия фото
        model = "gpt-4o" if photos_base64 else "gpt-4o"
        
        # Отправляем запрос к OpenAI через прокси
        logger.info(f"Отправляем запрос к OpenAI через прокси: {PROXY_URL}")
        
        # Формируем системный промпт
        channel_context = f"\nО канале: {channel_description}" if channel_description else ""
        
        system_prompt = f"""Ты умный и живой человек, который комментирует посты в Telegram канале. Твоя задача - писать короткие, яркие и человеческие комментарии.

Название канала: {channel_name}
Описание канала: {channel_context}

ПРАВИЛА КОММЕНТАРИЕВ:
- Длина: 2-6 слов максимум
- Стиль: живой, эмоциональный, как настоящий человек
- Используй emoji, но не всегда: 😁⚡️🔥😂💪🎯🚀💡👍👏
- Показывай эмоции и реакцию
- Будь конкретным и по делу
- Избегай формальности и "ботности"

Если в посте есть медиа-группа - проанализируй вопрос и что на них изображено

Напиши короткий живой комментарий к этому посту:"""

        # Формируем input для Responses API
        if photos_base64:
            # Если есть фото, используем формат с изображениями
            input_content = [
                { "type": "input_text", "text": f"{system_prompt}\n\n{text}" }
            ]
            
            # Добавляем все фото
            for photo_base64 in photos_base64:
                input_content.append({
                    "type": "input_image",
                    "image_url": f"data:image/jpeg;base64,{photo_base64}"
                })
            
            response = await client.responses.create(
                model=model,
                input=[{
                    "role": "user",
                    "content": input_content
                }]
            )
        else:
            # Если нет фото, используем простой текстовый input
            response = await client.responses.create(
                model=model,
                input=f"{system_prompt}\n\n{text}"
            )

        comment = response.output_text.strip()
        logger.info(f"Сгенерирован комментарий: {comment[:50]}...")
        
        return comment

    except Exception as e:
        logger.error(f"Ошибка при генерации комментария: {e}")
        return "Интересный пост! 👍"


def image_to_base64(image_path: str) -> str:
    """
    Конвертирует изображение в base64
    
    Args:
        image_path: Путь к изображению
    
    Returns:
        str: Изображение в формате base64
    """
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except Exception as e:
        logger.error(f"Ошибка при конвертации изображения в base64: {e}")
        return None


async def close_http_client():
    """Закрывает HTTP клиент (если используется глобальный)"""
    # В текущей реализации клиент создается локально для каждого запроса
    # поэтому эта функция не нужна, но оставлена для совместимости
    pass
