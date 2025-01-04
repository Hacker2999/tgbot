from datetime import datetime
from enum import member
from html.entities import html5
from itertools import count
from types import NoneType
from venv import create

from aiogram import Router, Bot
from aiogram.loggers import event
from aiogram.methods import GetMyDefaultAdministratorRights
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated
from aiogram.filters import Command, ChatMemberUpdatedFilter, IS_ADMIN, MEMBER
from aiogram.filters import IS_MEMBER, IS_NOT_MEMBER
import random
from peewee import *
from aiogram.utils.formatting import sizeof
from aiogram.utils.keyboard import InlineKeyboardBuilder

from baneks_api import fetch_random_joke
from model import TextModel, BotStatus, AnekModel

builder = InlineKeyboardBuilder()
router = Router()

LINKS = [
    ("Полезная ссылка", "https://example.com"),
    ("Бесполезная ссылка", "https://example.org"),
]


@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def handle_member_join(event: ChatMemberUpdated, bot: Bot):
    if event.new_chat_member:
        if event.new_chat_member.user.id == bot.id:
            await bot.send_message(
                chat_id=event.chat.id,
                text=f"Вы добавили отвального бота себе в чат\n"
                     f"Для начала выдайте боту права администратора\n"
                     f"После этого введите команду /welcome для знакомства со мной")

        else:
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
    if message.reply_to_message and message.reply_to_message.text:
        WELCOME_MESSAGE = message.reply_to_message.text
    elif message.text and len(message.text.split(maxsplit=1)) > 1:
        WELCOME_MESSAGE = message.text.split(maxsplit=1)[1]
    else:
        await message.reply("Приветствие не обновлено!")
        return

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
    if message.reply_to_message and message.reply_to_message.text:
        GOODBYE_MESSAGE = message.reply_to_message.text
    elif message.text and len(message.text.split(maxsplit=1)) > 1:
        GOODBYE_MESSAGE = message.text.split(maxsplit=1)[1]
    else:
        await message.reply("Прощание не обновлено!")
        return

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

@router.message(Command("anekdot"))
async def i_want_anekdot(message: Message):
    userId = message.from_user.id
    q2 =(AnekModel.select(AnekModel.count)
        .where(AnekModel.user_id == userId)
        .first()
    )
    count_qu = q2.count
    print(count_qu)
    if count_qu < 3:
        try:
            anekdot = await fetch_random_joke()
            q = (AnekModel
            .insert({
                AnekModel.created_at: fn.now(),  # Используем SQL-функцию now()
                AnekModel.user_id: userId,
                AnekModel.count: 1
            })
            .on_conflict(
                conflict_target=[AnekModel.user_id],
                preserve=[AnekModel.created_at],
                update={AnekModel.count: AnekModel.count + 1}
            ))
            q.execute()
            await message.reply(anekdot,parse_mode="markdown")
        except Exception as e:
            print(e)
            print(datetime.now().date())
            await message.reply(f"Анекдота не будет")
    else:
        await message.reply(f"Анекдота не будет. Превышен лимит на день!")