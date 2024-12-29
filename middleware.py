from aiogram import BaseMiddleware
from aiogram.types import Message
from collections import defaultdict
import datetime

class AntiSpamMiddleware(BaseMiddleware):
    def __init__(self, spam_limit=5):
        self.spam_limit = spam_limit
        self.user_messages = defaultdict(list)
        super().__init__()

    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            user_id = event.from_user.id
            now = datetime.datetime.now()
            self.user_messages[user_id] = [
                msg_time for msg_time in self.user_messages[user_id] if (now - msg_time).seconds < 60
            ]
            self.user_messages[user_id].append(now)

            if len(self.user_messages[user_id]) > self.spam_limit:
                await event.chat.ban(user_id,datetime.timedelta(seconds=30))
                await event.reply(f"{event.from_user.first_name} забанен за спам!")
                return
        return await handler(event, data)
