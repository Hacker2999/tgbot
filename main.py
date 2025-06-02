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
    """Получить API токен из config или переменных окружения."""
    token = API_TOKEN
    if not token:
        logger.error("API токен не установлен! Установите API_TOKEN в config.py.")
    return token

async def notify_all_chats(bot: Bot, text: str):
    try:
        chat_ids = [chat.chat_id for chat in Chat_listModel.select(Chat_listModel.chat_id)]
        for chat_id in chat_ids:
            try:
                await bot.send_message(chat_id, text)
            except Exception as e:
                logger.warning(f"Не удалось уведомить чат {chat_id}: {e}")
    except Exception as e:
        logger.error(f"Не удалось получить список чатов для уведомлений: {e}")

async def main() -> None:
    """Запуск Telegram-бота с корректным завершением работы."""
    token = get_api_token()
    if not token:
        return
    bot = Bot(token=token)
    dp = Dispatcher()
    dp.include_router(router)
    dp.message.middleware(AntiSpamMiddleware())

    stop_event = asyncio.Event()

    def _signal_handler(*_):
        logger.info("Получен сигнал завершения. Остановка бота...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Обработчики сигналов недоступны на Windows для некоторых сигналов
            pass

    logger.info("Бот запускается...")
    await bot.send_message(CHANNEL_CHAT_ID, "🤖 Бот запущен и готов к работе!")
    try:
        await dp.start_polling(bot, shutdown_event=stop_event)
    except Exception as e:
        logger.error(f"Бот остановлен с ошибкой: {e}")
    finally:
        logger.info("Бот завершил работу.")
        await bot.send_message(CHANNEL_CHAT_ID, "⚠️ Бот завершил работу. До скорой встречи!")

if __name__ == "__main__":
    asyncio.run(main())
