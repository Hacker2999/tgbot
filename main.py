import asyncio
import logging
import os
import signal
from typing import Optional

from aiogram import Bot, Dispatcher
from config import API_TOKEN, CHANNEL_CHAT_ID
from handlers import router
from middleware import AntiSpamMiddleware
from model import Chat_listModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_api_token() -> Optional[str]:
    """Get the API token from config or environment."""
    token = API_TOKEN
    if not token:
        logger.error("API token is not set! Set API_TOKEN in config.py.")
    return token

async def notify_all_chats(bot: Bot, text: str):
    try:
        chat_ids = [chat.chat_id for chat in Chat_listModel.select(Chat_listModel.chat_id)]
        for chat_id in chat_ids:
            try:
                await bot.send_message(chat_id, text)
            except Exception as e:
                logger.warning(f"Failed to notify chat {chat_id}: {e}")
    except Exception as e:
        logger.error(f"Failed to fetch chat list for notifications: {e}")

async def main() -> None:
    """Start the Telegram bot with graceful shutdown."""
    token = get_api_token()
    if not token:
        return
    bot = Bot(token=token)
    dp = Dispatcher()
    dp.include_router(router)
    dp.message.middleware(AntiSpamMiddleware())

    stop_event = asyncio.Event()

    def _signal_handler(*_):
        logger.info("Received shutdown signal. Stopping bot...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Signal handlers are not available on Windows for some signals
            pass

    logger.info("Bot is starting...")
    await bot.send_message(CHANNEL_CHAT_ID, "🤖 Бот запущен и готов к работе!")
    try:
        await dp.start_polling(bot, shutdown_event=stop_event)
    except Exception as e:
        logger.error(f"Bot stopped with error: {e}")
    finally:
        logger.info("Bot shutdown complete.")
        await bot.send_message(CHANNEL_CHAT_ID, "⚠️ Бот завершил работу. До скорой встречи!")

if __name__ == "__main__":
    asyncio.run(main())
