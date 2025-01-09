from aiogram import Bot, Dispatcher, Router

from config import API_TOKEN
from handlers import router
from middleware import AntiSpamMiddleware
import asyncio

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

dp.include_router(router)
dp.message.middleware(AntiSpamMiddleware())

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
