import logging
from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict

from model import BanList

logger = logging.getLogger(__name__)

class AntiSpamMiddleware(BaseMiddleware):
    """
    Мидлвар для предотвращения спама: мутит пользователей, которые отправляют повторяющиеся сообщения.
    Отслеживает сообщения пользователей и применяет возрастающие наказания за повторный спам.
    Теперь отслеживает спам по тексту, стикерам, гифкам и картинкам.
    """
    # Длительности мута для каждого уровня наказания
    MUTE_DURATIONS = {
        1: timedelta(days=1),
        2: timedelta(weeks=1),
        3: timedelta(days=30),
        4: timedelta(days=365),
    }
    DEFAULT_MUTE_DURATION = timedelta(days=365)

    def __init__(self, spam_limit: int = 5) -> None:
        self.spam_limit = spam_limit  # Лимит одинаковых сообщений в минуту
        self.user_messages: Dict[int, list] = defaultdict(list)  # user_id -> [(datetime, content_id)]
        self.user_penalties: Dict[int, int] = defaultdict(int)  # user_id -> количество наказаний
        super().__init__()

    async def is_admin(self, bot: Bot, chat_id: int, user_id: int) -> bool:
        """Проверить, является ли пользователь админом в чате."""
        try:
            chat_admins = await bot.get_chat_administrators(chat_id)
            return any(admin.user.id == user_id for admin in chat_admins)
        except TelegramBadRequest:
            return False
        except Exception as e:
            logger.error(f"Ошибка при проверке статуса администратора: {e}")
            return False

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            user_id = event.from_user.id
            user_name = event.from_user.first_name
            chat_id = event.chat.id
            bot: Bot = data['bot']
            now = datetime.now(timezone.utc)

            # Пропустить проверку спама для админов
            if await self.is_admin(bot, chat_id, user_id):
                return await handler(event, data)

            # --- Новый блок: определяем content_id для разных типов сообщений ---
            if event.text:
                content_id = f"text:{event.text}"
            elif event.sticker:
                content_id = f"sticker:{event.sticker.file_unique_id}"
            elif event.animation:
                content_id = f"animation:{event.animation.file_unique_id}"
            elif event.photo:
                # Для фото берём file_unique_id самого большого изображения
                content_id = f"photo:{event.photo[-1].file_unique_id}"
            else:
                content_id = None

            if content_id is None:
                return await handler(event, data)

            # Сохраняем content_id пользователя
            self.user_messages[user_id].append((now, content_id))

            # Оставляем только сообщения за последнюю минуту
            self.user_messages[user_id] = [
                (msg_time, msg_content)
                for msg_time, msg_content in self.user_messages[user_id]
                if (now - msg_time).total_seconds() < 60
            ]

            # Проверка на повторяющийся спам
            messages_contents = [msg_content for _, msg_content in self.user_messages[user_id]]
            if (
                len(messages_contents) >= self.spam_limit and
                len(set(messages_contents[-self.spam_limit:])) == 1
            ):
                self.user_penalties[user_id] += 1
                penalty_level = self.user_penalties[user_id]
                mute_duration = self.MUTE_DURATIONS.get(penalty_level, self.DEFAULT_MUTE_DURATION)
                mute_start = now
                mute_end = now + mute_duration

                try:
                    await bot.restrict_chat_member(
                        chat_id=chat_id,
                        user_id=user_id,
                        permissions={"can_send_messages": False},
                        until_date=mute_end
                    )
                    q = (
                        BanList
                        .insert({
                            BanList.user_id: user_id,
                            BanList.ban_start: mute_start,
                            BanList.ban_end: mute_end,
                            BanList.reason: "Спам",
                            BanList.ban_from: str(chat_id)
                        })
                        .on_conflict(
                            conflict_target=[BanList.user_id],
                            update={
                                BanList.ban_start: mute_start,
                                BanList.ban_end: mute_end,
                                BanList.reason: "Спам",
                                BanList.ban_from: str(chat_id)
                            }
                        )
                    )
                    q.execute()
                    logger.info(f"Пользователь {user_name} ({user_id}) замучен в чате {chat_id} за спам на {mute_duration}.")
                    # Удалить спам-сообщение
                    try:
                        await event.delete()
                    except Exception as del_err:
                        logger.warning(f"Не удалось удалить спам-сообщение: {del_err}")
                    # Уведомить пользователя
                    try:
                        await bot.send_message(user_id, f"Вы были замучены за спам в чате {chat_id} на {mute_duration}.")
                    except Exception as notify_err:
                        logger.warning(f"Не удалось уведомить пользователя о муте: {notify_err}")
                    # Сообщить в чат
                    unmute_time = mute_end.strftime('%d.%m.%Y %H:%M')
                    await bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"Пользователь <b>{user_name}</b> (id: <code>{user_id}</code>) был замучен за спам на {mute_duration}.\n"
                            f"Размут: <b>{unmute_time}</b>"
                        ),
                        parse_mode="HTML"
                    )
                    await event.reply(f"Мут за спам {user_name} на {mute_duration}.")
                except Exception as e:
                    logger.error(f"Не удалось замутить пользователя {user_id} в чате {chat_id}: {e}")
                return

        return await handler(event, data)
