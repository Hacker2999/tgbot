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
    Middleware to prevent spam by muting users who send repeated messages.
    Tracks user messages and applies increasing penalties for repeated spam.
    """
    # Mute durations for each penalty level
    MUTE_DURATIONS = {
        1: timedelta(days=1),
        2: timedelta(weeks=1),
        3: timedelta(days=30),
        4: timedelta(days=365),
    }
    DEFAULT_MUTE_DURATION = timedelta(days=365)

    def __init__(self, spam_limit: int = 5) -> None:
        self.spam_limit = spam_limit  # Limit of identical messages per minute
        self.user_messages: Dict[int, list] = defaultdict(list)  # user_id -> [(datetime, text)]
        self.user_penalties: Dict[int, int] = defaultdict(int)  # user_id -> penalty count
        super().__init__()

    async def is_admin(self, bot: Bot, chat_id: int, user_id: int) -> bool:
        """Check if a user is an admin in the chat."""
        try:
            chat_admins = await bot.get_chat_administrators(chat_id)
            return any(admin.user.id == user_id for admin in chat_admins)
        except TelegramBadRequest:
            return False
        except Exception as e:
            logger.error(f"Error checking admin status: {e}")
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

            # Skip spam check for admins
            if await self.is_admin(bot, chat_id, user_id):
                return await handler(event, data)

            # Store the user's message
            self.user_messages[user_id].append((now, event.text))

            # Keep only messages from the last minute
            self.user_messages[user_id] = [
                (msg_time, msg_text)
                for msg_time, msg_text in self.user_messages[user_id]
                if (now - msg_time).total_seconds() < 60
            ]

            # Check for repeated spam
            messages_texts = [msg_text for _, msg_text in self.user_messages[user_id]]
            if (
                len(messages_texts) >= self.spam_limit and
                len(set(messages_texts[-self.spam_limit:])) == 1
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
                    logger.info(f"Muted user {user_name} ({user_id}) in chat {chat_id} for spam for {mute_duration}.")
                    # Delete the spam message
                    try:
                        await event.delete()
                    except Exception as del_err:
                        logger.warning(f"Failed to delete spam message: {del_err}")
                    # Notify the user
                    try:
                        await bot.send_message(user_id, f"Вы были замучены за спам в чате {chat_id} на {mute_duration}.")
                    except Exception as notify_err:
                        logger.warning(f"Failed to notify user about mute: {notify_err}")
                    await event.reply(f"Мут за спам {user_name} на {mute_duration}.")
                except Exception as e:
                    logger.error(f"Failed to mute user {user_id} in chat {chat_id}: {e}")
                return

        return await handler(event, data)
