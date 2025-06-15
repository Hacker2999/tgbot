import asyncio
import logging
import signal
from typing import Optional
from datetime import datetime, time, timedelta
import pytz
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import API_TOKEN, CHANNEL_CHAT_ID
from handlers import router
from middleware import AntiSpamMiddleware
from model import Chat_listModel
from ignore_old_messages import IgnoreOldMessagesMiddleware
from utils import award_size_top_exp

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

async def send_channel_message(bot: Bot, text: str) -> None:
    """Отправка сообщения в канал с обработкой ошибок."""
    if not CHANNEL_CHAT_ID:
        logger.error("CHANNEL_CHAT_ID не установлен в config.py!")
        return
    try:
        await bot.send_message(CHANNEL_CHAT_ID, text)
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение в канал: {e}")

async def schedule_awards(bot: Bot, chat_id: int):
    """Планировщик для начисления наград в 20:00 по МСК."""
    while True:
        try:
            moscow_tz = pytz.timezone('Europe/Moscow')
            now = datetime.now(moscow_tz)
            target_time = time(20, 0)  # 20:00
            
            # Если текущее время больше 20:00, ждем до следующего дня
            if now.time() > target_time:
                next_run = datetime.combine(now.date() + timedelta(days=1), target_time)
            else:
                next_run = datetime.combine(now.date(), target_time)
            
            # Переводим в UTC для расчета задержки
            next_run = moscow_tz.localize(next_run).astimezone(pytz.UTC)
            now = now.astimezone(pytz.UTC)
            
            # Ждем до следующего запуска
            delay = (next_run - now).total_seconds()
            await asyncio.sleep(delay)
            
            # Начисляем награды
            await award_size_top_exp(bot, chat_id)
            
        except Exception as e:
            logger.error(f"Ошибка в планировщике наград: {e}")
            await asyncio.sleep(60)  # Ждем минуту перед повторной попыткой

async def main() -> None:
    """Запуск Telegram-бота с корректным завершением работы."""
    token = get_api_token()
    if not token:
        return
    bot = Bot(token=token)
    dp = Dispatcher()
    dp.include_router(router)
    dp.update.middleware(IgnoreOldMessagesMiddleware())
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
    await send_channel_message(bot, "🤖 Бот запущен и готов к работе!")
    
    # Запускаем планировщик наград
    asyncio.create_task(schedule_awards(bot, CHANNEL_CHAT_ID))
    
    try:
        await dp.start_polling(bot, shutdown_event=stop_event)
    except Exception as e:
        logger.error(f"Бот остановлен с ошибкой: {e}")
    finally:
        logger.info("Бот завершил работу.")
        await send_channel_message(bot, "⚠️ Бот завершил работу. До скорой встречи!")

if __name__ == "__main__":
    asyncio.run(main())
