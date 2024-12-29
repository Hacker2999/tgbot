from aiogram import Router, Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated
from aiogram.filters import Command, ChatMemberUpdatedFilter
from aiogram.filters import IS_MEMBER, IS_NOT_MEMBER
import random
from peewee import *
from aiogram.utils.formatting import sizeof
from aiogram.utils.keyboard import InlineKeyboardBuilder

from model import TextModel

builder = InlineKeyboardBuilder()
router = Router()


LINKS = [
    ("Полезная ссылка", "https://example.com"),
    ("Бесполезная ссылка", "https://example.org"),
]


@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def handle_member_join(event: ChatMemberUpdated, bot: Bot):
    q = (TextModel
         .select(TextModel.text_of)
         .where(TextModel.target == "welcome_message")
         .first()
         )
    WELCOME_MESSAGE = q.text_of

    await bot.send_message(
        chat_id=event.chat.id,
        text=f"{WELCOME_MESSAGE}, {event.from_user.first_name}!")


@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def handle_member_leave(event: ChatMemberUpdated, bot: Bot):
    q = (TextModel
         .select(TextModel.text_of)
         .where(TextModel.target == "bye_message")
         .first()
         )

    GOODBYE_MESSAGE = q.text_of

    await bot.send_message(
        chat_id=event.chat.id,
        text=f"{GOODBYE_MESSAGE}, {event.from_user.first_name}!"
    )


@router.message(Command("set_welcome"))
async def set_welcome(message: Message):
    WELCOME_MESSAGE = message.text.split(maxsplit=1)[1]
    q = (TextModel
         .update({TextModel.text_of: WELCOME_MESSAGE})
         .where(TextModel.target == "welcome_message"))
    try:
        q.execute()
        await message.reply("Приветствие обновлено!")
    except Exception as e:
        await message.reply("Приветствие не обновлено!")


@router.message(Command("set_bye"))
async def set_bye(message: Message):
    global GOODBYE_MESSAGE
    GOODBYE_MESSAGE = message.text.split(maxsplit=1)[1]
    q = (TextModel
         .update({TextModel.text_of: GOODBYE_MESSAGE})
         .where(TextModel.target == "bye_message"))
    try:
        q.execute()
        await message.reply("Прощание обновлено!")
    except Exception as e:
        await message.reply("Прощание не обновлено!")


@router.message(Command("rules"))
async def send_rules(message: Message):
    await message.reply(RULES)


@router.message(Command("links"))
async def send_links(message: Message):
    builder.adjust(len(LINKS))
    for text, url in LINKS:
        builder.button(text=text, url=url)
    await message.reply("Ссылки:", reply_markup=builder.as_markup())


@router.message(Command("size"))
async def measure_size(message: Message):
    username = message.from_user.first_name or message.from_user.username
    with open("xyz.txt", "r", encoding="utf-8") as file:
        lines = [line.strip() for line in file]
    size = random.randint(-1, 50)
    await message.reply(f"{random.choice(lines)} у {username}'a: {size} см")
