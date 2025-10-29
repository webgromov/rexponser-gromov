from tortoise.models import Model
from tortoise import fields
from enum import Enum


class CommentStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class Comment(Model):
    """Модель для хранения комментариев к постам каналов"""
    
    id = fields.IntField(pk=True)
    channel_id = fields.BigIntField(description="ID канала")
    message_id = fields.BigIntField(description="ID сообщения в канале")
    generated_comment = fields.TextField(description="Сгенерированный комментарий")
    post_text = fields.TextField(null=True, description="Текст поста")
    photo_path = fields.TextField(null=True, description="Путь к фото поста")
    status = fields.CharEnumField(CommentStatus, default=CommentStatus.PENDING, description="Статус комментария")
    sent_message_id = fields.BigIntField(null=True, description="ID отправленного комментария в чате")
    created_at = fields.DatetimeField(auto_now_add=True, description="Дата создания")
    sent_at = fields.DatetimeField(null=True, description="Дата отправки комментария")
    
    class Meta:
        table = "comments"
        table_description = "Таблица для хранения комментариев к постам каналов"
    
    def __str__(self):
        return f"Comment {self.id} for channel {self.channel_id}, message {self.message_id}"
