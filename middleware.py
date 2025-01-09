from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message
from collections import defaultdict
import datetime

from model import BanList


class AntiSpamMiddleware(BaseMiddleware):
    def __init__(self, spam_limit=5):
        self.spam_limit = spam_limit  # Лимит сообщений
        self.user_messages = defaultdict(list)  # История сообщений пользователей
        self.user_penalties = defaultdict(int)  # Количество нарушений
        super().__init__()

    async def is_admin(self, bot, chat_id, user_id):
        """Проверяет, является ли пользователь администратором чата."""
        try:
            chat_admins = await bot.get_chat_administrators(chat_id)
            return any(admin.user.id == user_id for admin in chat_admins)
        except TelegramBadRequest:
            return False

    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            user_id = event.from_user.id
            user_name = event.from_user.first_name
            chat_id = event.chat.id
            bot = data['bot']  # Получаем объект бота
            now = datetime.datetime.now()

            # Проверка, является ли пользователь администратором
            if await self.is_admin(bot, chat_id, user_id):
                return await handler(event, data)

            # Сохраняем последнее сообщение пользователя
            self.user_messages[user_id].append((now, event.text))

            # Оставляем только сообщения за последнюю минуту
            self.user_messages[user_id] = [
                (msg_time, msg_text)
                for msg_time, msg_text in self.user_messages[user_id]
                if (now - msg_time).seconds < 60
            ]

            # Проверяем количество одинаковых сообщений
            messages_texts = [msg_text for _, msg_text in self.user_messages[user_id]]
            if len(messages_texts) >= self.spam_limit and len(set(messages_texts[-self.spam_limit:])) == 1:
                # Увеличиваем счетчик нарушений
                self.user_penalties[user_id] += 1

                # Определяем длительность мута
                penalty_level = self.user_penalties[user_id]
                mute_duration = {
                    1: datetime.timedelta(days=1),
                    2: datetime.timedelta(weeks=1),
                    3: datetime.timedelta(days=30),
                    4: datetime.timedelta(days=365)
                }.get(penalty_level, datetime.timedelta(days=365))  # Длительность увеличивается до года

                # Начало и конец мута
                mute_start = now
                mute_end = now + mute_duration

                # Мут пользователя
                await bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    permissions={"can_send_messages": False},
                    until_date=mute_end
                )

                q = (BanList
                .insert({
                    BanList.user_id: user_id,
                    BanList.ban_start: mute_start,
                    BanList.ban_end: mute_end,
                    BanList.reason: "Спам",
                    BanList.ban_from: str(chat_id)
                })
                .on_conflict(
                    conflict_target=[BanList.user_id],  # Конфликт по user_id
                    update={
                        BanList.ban_start: mute_start,
                        BanList.ban_end: mute_end,
                        BanList.reason: "Спам",
                        BanList.ban_from: str(chat_id)
                    }
                )
                )
                q.execute()

                # Уведомление
                await event.reply(f"Мут за спам {user_name} на {mute_duration}.")
                return

        return await handler(event, data)
