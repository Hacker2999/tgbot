from aiogram import BaseMiddleware
from datetime import datetime, timezone

BOT_START_TIME = datetime.now(timezone.utc)

class IgnoreOldMessagesMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        message = data.get("event_message") or data.get("message") or event
        if hasattr(message, "date") and message.date < BOT_START_TIME:
            return  # Игнорируем старое сообщение
        return await handler(event, data) 