import asyncio
import logging
import os
import signal
from typing import Optional

from aiogram import Bot, Dispatcher
from config import API_TOKEN
from handlers import router
from middleware import AntiSpamMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_api_token() -> Optional[str]:
    """Get the API token from config or environment."""
    token = API_TOKEN or os.getenv("API_TOKEN")
    if not token:
        logger.error("API token is not set! Set API_TOKEN in config.py or as an environment variable.")
    return token

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
    try:
        await dp.start_polling(bot, shutdown_event=stop_event)
    except Exception as e:
        logger.error(f"Bot stopped with error: {e}")
    finally:
        logger.info("Bot shutdown complete.")

if __name__ == "__main__":
    asyncio.run(main())
