import asyncio
import logging
import signal
from typing import Optional
from datetime import datetime, time, timedelta
import pytz
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import API_TOKEN
from handlers import router
from middleware import AntiSpamMiddleware
from model import Chat_listModel, db
from ignore_old_messages import IgnoreOldMessagesMiddleware
from utils import award_size_top_exp, kick_for_unactive

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
    try:
        # Отправляем уведомление во все чаты из базы данных
        await notify_all_chats(bot, text)
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение в чаты: {e}")

async def auto_task(bot: Bot):
    """Планировщик для задач в 18:00 по МСК."""
    while True:
        try:
            moscow_tz = pytz.timezone('Europe/Moscow')
            now = datetime.now(moscow_tz)
            target_time = time(18, 00)  # 18:00
            
            # Если текущее время больше 18:00, ждем до следующего дня
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
            
            # Получаем все чаты из базы данных
            chat_ids = [chat.chat_id for chat in Chat_listModel.select(Chat_listModel.chat_id)]
            
            # Начисляем награды для каждого чата
            for chat_id in chat_ids:
                try:
                    await award_size_top_exp(bot, chat_id)
                    await kick_for_unactive(bot, chat_id)
                except Exception as e:
                    logger.error(f"Ошибка при обработке чата {chat_id}: {e}")
            
        except Exception as e:
            logger.error(f"Ошибка в планировщике наград: {e}")
            await asyncio.sleep(60)  # Ждем минуту перед повторной попыткой

async def main() -> None:
    """Запуск Telegram-бота с корректным завершением работы."""
    token = get_api_token()
    if not token:
        return
        
    # Инициализируем подключение к базе данных
    try:
        db.connect()
        logger.info("Подключение к базе данных установлено")
    except Exception as e:
        logger.error(f"Ошибка подключения к базе данных: {e}")
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
    asyncio.create_task(auto_task(bot))
    
    try:
        await dp.start_polling(bot, shutdown_event=stop_event)
    except Exception as e:
        logger.error(f"Бот остановлен с ошибкой: {e}")
    finally:
        logger.info("Бот завершил работу.")
        await send_channel_message(bot, "⚠️ Бот завершил работу. До скорой встречи!")
        # Закрываем подключение к базе данных
        try:
            db.close()
            logger.info("Подключение к базе данных закрыто")
        except Exception as e:
            logger.error(f"Ошибка при закрытии подключения к базе данных: {e}")

if __name__ == "__main__":
    asyncio.run(main())
