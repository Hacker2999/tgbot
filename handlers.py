from datetime import datetime

from aiogram import Router, Bot
from aiogram.enums import ChatAction
from aiogram.loggers import event
from aiogram.methods import PinChatMessage
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated, BotCommand, \
    MenuButtonCommands, ChatPhoto
from aiogram.filters import Command, ChatMemberUpdatedFilter, IS_ADMIN, MEMBER, Filter
from aiogram.filters import IS_MEMBER, IS_NOT_MEMBER, Command
import random

from aiogram import F
from peewee import *
from aiogram.utils.formatting import sizeof
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pyexpat.errors import messages

from baneks_api import fetch_random_joke
from model import TextModel, AnekModel, User_listModel, Chat_listModel, Button_listModel
from utils import quota_check

router = Router()

LINKS = [
    ("Полезная ссылка", "https://example.com"),
    ("Бесполезная ссылка", "https://example.org"),
]

admin_commands = [
        BotCommand(command="stat",description="Вывод статистики пользователя"),
        BotCommand(command="set_welcome",description="Изменить приветственное сообщение"),
        BotCommand(command="set_bye",description="Изменить прощальное сообщение"),
        BotCommand(command="rules",description="Правила"),
        BotCommand(command="size",description="Команда по измерению своего бубуя"),
        BotCommand(command="links",description="Полезные ссылки"),
        BotCommand(command="anekdot",description="Внимание,анекдот"),
]
admin_menu_button = MenuButtonCommands(commands=admin_commands)

user_commands = [
        BotCommand(command="stat",description="Вывод статистики пользователя"),
        BotCommand(command="rules",description="Правила"),
        BotCommand(command="size",description="Команда по измерению своего бубуя"),
        BotCommand(command="links",description="Полезные ссылки"),
        BotCommand(command="anekdot",description="Внимание,анекдот"),
]



@router.my_chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def handle_member_join(event: ChatMemberUpdated,bot: Bot):
    if event.new_chat_member:
        if event.new_chat_member.user.id == bot.id:
            q = (Chat_listModel.insert({
                Chat_listModel.created_at: fn.now(),
                Chat_listModel.chat_id: event.chat.id
            })
            .on_conflict(
                conflict_target=[Chat_listModel.chat_id],
                update={User_listModel.created_at: fn.now()}
            )
            )
            q.execute()
            await bot.send_message(
                chat_id=event.chat.id,
                text=f"Вы добавили отвального бота себе в чат")

        else:
            q = (TextModel
                 .select(TextModel.text_of)
                 .where(TextModel.target == "welcome_message")
                 .first()
                 )
            WELCOME_MESSAGE = q.text_of
            q2 = (User_listModel
            .insert({
                User_listModel.created_at: fn.now(),
                User_listModel.user_id: event.from_user.id,
            })
            .on_conflict(
                conflict_target=[User_listModel.user_id],
                update={User_listModel.created_at: fn.now()}
            )
            )
            q2.execute()

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
    try:
        q2 = (User_listModel
              .select(User_listModel.created_at, User_listModel.message_count)
              .where(User_listModel.user_id == event.from_user.id)
              .first()
              )
        time_withus = datetime.astimezone(datetime.now()) - q2.created_at
        days = time_withus.days
        hours = time_withus.seconds // 3600
        minutes = (time_withus.seconds % 3600) // 60
        await bot.send_message(
            chat_id=event.chat.id,
            text=f"{GOODBYE_MESSAGE}, {event.from_user.first_name}!\n"
                 f"Кол-во сообщений: {q2.message_count}\n"
                 f"Был с нами: \n"
                 f"Дней: {days}\n"
                 f"Часов: {hours}\n"
                 f"Минут: {minutes}\n"
        )
    except Exception as e:
        print(e)
        await bot.send_message(
            chat_id=event.chat.id,
            text=f"{GOODBYE_MESSAGE}, {event.from_user.first_name}!\n"
                 f"Легенды не вмирают"
        )

@router.message(Command(BotCommand(command="stat", description="Вывод статистики пользователя")))
async def stat(message: Message, bot: Bot):
    try:
        q = (User_listModel
             .select(User_listModel.created_at, User_listModel.message_count)
             .where(User_listModel.user_id == message.from_user.id)
             .first()
             )
        time_withus = datetime.astimezone(datetime.now()) - q.created_at
        days = time_withus.days
        hours = time_withus.seconds // 3600
        minutes = (time_withus.seconds % 3600) // 60
        await bot.send_message(
            chat_id=message.chat.id,
            text=f"Статистика, {message.from_user.first_name}'a:\n"
                 f"Кол-во сообщений: {q.message_count}\n"
                 f"C нами уже: \n"
                 f"Дней: {days}\n"
                 f"Часов: {hours}\n"
                 f"Минут: {minutes}\n"

        )
    except Exception as e:
        print(e)
        await bot.send_message(
            chat_id=message.chat.id,
            text=f"Вы древний мудрый дуб, живите теперь с этим...\n"
        )
    print(message.chat.type)


@router.message(Command(BotCommand(command="set_welcome", description="Изменить приветственное сообщение")))
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


@router.message(Command(BotCommand(command="set_bye", description="Изменить прощальное сообщение")))
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

@router.message(Command(BotCommand(command="add_button", description="Добавить кнопку в ссылках")))
async def add_button(message: Message):
    try:
        text = message.text.removeprefix('/add_button ').strip()
        parts = text.split('" "')

        # Убираем кавычки
        button_name = parts[0].strip('"')
        link = parts[1].strip('"')

        print(f"Название кнопки: {button_name}")
        print(f"Ссылка: {link}")
        q = (Button_listModel
        .insert({
            Button_listModel.button_name: button_name,
            Button_listModel.button_link: link,
        })
        .on_conflict(
            conflict_target=[Button_listModel.button_link],
            update={
                Button_listModel.button_name: button_name,
                Button_listModel.button_link: link,
            }
        )
        )
        q.execute()
        await message.reply(f"Добавлена кнопка: {button_name}")
    except Exception as e:
        print(e)

@router.message(Command(BotCommand(command="del_button", description="Удалить кнопку в ссылках")))
async def del_button(message: Message):
    try:
        text = message.text.removeprefix('/del_button ').strip()

        q = (Button_listModel.delete().where(Button_listModel.button_name == text))
        q.execute()
        await message.reply(f"Удалена кнопка: {text}")
    except Exception as e:
        print(e)



@router.message(Command(BotCommand(command="rules",description="Правила")))
async def send_rules(message: Message):
    q = (TextModel
         .select(TextModel.text_of)
         .where(TextModel.target == "rules")
         .first()
         )
    await message.reply(q.text_of)


@router.message(Command(BotCommand(command="links", description="Полезные ссылки")))
async def send_links(message: Message):
    query = Button_listModel.select()
    builder = InlineKeyboardBuilder()
    result = [
        {
            "button_name": record.button_name,
            "button_link": record.button_link,
        }
        for record in query
    ]
    link_list = result
    builder.adjust(len(link_list))
    for record in link_list:
        button_name = record["button_name"]
        button_link = record["button_link"]
        builder.button(text=button_name, url=button_link)
    await message.reply("Ссылки:", reply_markup=builder.as_markup())


@router.message(Command(BotCommand(command="size", description="Команда по измерению своего бубуя")))
async def measure_size(message: Message):
    print(message.chat.id)
    username = message.from_user.first_name or message.from_user.username
    with open("xyz.txt", "r", encoding="utf-8") as file:
        lines = [line.strip() for line in file]
    size = random.randint(-1, 50)
    await message.reply(f"{random.choice(lines)} у {username}'a: {size} см")


@router.message(Command(BotCommand(command="anekdot", description="Внимание, АНЕКДОТ!!!")))
async def i_want_anekdot(message: Message):
    userId = message.from_user.id
    q2 = (AnekModel.select(AnekModel.count)
          .where(AnekModel.user_id == userId)
          .first()
          )
    count_qu = q2.count

    if quota_check(userId, count_qu):
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
            await message.reply(anekdot, parse_mode="markdown")
        except Exception as e:
            print(e)
            print(datetime.now().date())
            await message.reply(f"Анекдота не будет. Системная ошибка, обратитесь к отвальному создателю")
    else:
        await message.reply(f"Анекдота не будет. Превышен лимит на день!")


# @router.message(F.sender_chat.type == "channel")
# async def pin_message(message: Message, bot:Bot):
#     try:
#         await bot.unpin_all_chat_messages(message.chat.id)
#         await bot.pin_chat_message(message.chat.id, message.message_id)
#         print(f"Сообщение от канала {message.sender_chat.title} закреплено.")
#     except Exception as e:
#         print(e)

@router.message()
async def messages_counter(message: Message, bot:Bot):

    try:
        q = (User_listModel
        .insert({
            User_listModel.created_at: fn.now(),
            User_listModel.user_id: message.from_user.id,
        })
        .on_conflict(
            conflict_target=[User_listModel.user_id],
            update={User_listModel.message_count: User_listModel.message_count + 1}
        )
        )
        q.execute()
    except Exception as e:
        print(e)
