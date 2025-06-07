from aiogram import BaseMiddleware
from datetime import datetime, timezone

BOT_START_TIME = datetime.now(timezone.utc)

class IgnoreOldMessagesMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        # Проверяем все типы событий, у которых есть поле date
        obj = data.get("event_message") or data.get("message") or data.get("event") or event
        # Для ChatMemberUpdated и CallbackQuery тоже есть date
        event_date = None
        if hasattr(obj, "date"):
            event_date = obj.date
        elif hasattr(obj, "message") and hasattr(obj.message, "date"):
            event_date = obj.message.date
        elif hasattr(obj, "edit_date"):
            event_date = obj.edit_date
        if event_date and event_date < BOT_START_TIME:
            return  # Игнорируем старое событие/сообщение/апдейт
        return await handler(event, data) 