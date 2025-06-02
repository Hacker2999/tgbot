import logging
from datetime import datetime, timedelta
import random
import re

from aiogram import Router, Bot, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated, BotCommand, MenuButtonCommands
from aiogram.filters import Command, ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from aiogram.utils.keyboard import InlineKeyboardBuilder
from peewee import fn

from baneks_api import fetch_random_joke
from model import TextModel, AnekModel, User_listModel, Chat_listModel, Button_listModel, SizeModel
from utils import quota_check
from config import RULES, API_TOKEN, SPAM_LIMIT, DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT

router = Router()
logger = logging.getLogger(__name__)

admin_commands = [
    BotCommand(command="stat", description="Вывод статистики пользователя"),
    BotCommand(command="set_welcome", description="Изменить приветственное сообщение"),
    BotCommand(command="set_bye", description="Изменить прощальное сообщение"),
    BotCommand(command="rules", description="Правила"),
    BotCommand(command="size", description="Команда по измерению своего бубуя"),
    BotCommand(command="links", description="Полезные ссылки"),
    BotCommand(command="anekdot", description="Внимание,анекдот"),
]
admin_menu_button = MenuButtonCommands(commands=admin_commands)

user_commands = [
    BotCommand(command="stat", description="Вывод статистики пользователя"),
    BotCommand(command="rules", description="Правила"),
    BotCommand(command="size", description="Команда по измерению своего бубуя"),
    BotCommand(command="links", description="Полезные ссылки"),
    BotCommand(command="anekdot", description="Внимание,анекдот"),
]

RULES_MESSAGE_ID = 1  # TODO: Set this to the actual message ID with the rules in your chat

def parse_time_arg(arg: str) -> timedelta:
    match = re.match(r"(\d+)\s*(min|h|d|w|m|y)?", arg)
    if not match:
        return None
    value, unit = match.groups()
    value = int(value)
    if unit == "min":
        return timedelta(minutes=value)
    elif unit == "h":
        return timedelta(hours=value)
    elif unit == "d":
        return timedelta(days=value)
    elif unit == "w":
        return timedelta(weeks=value)
    elif unit == "m":
        return timedelta(days=30*value)
    elif unit == "y":
        return timedelta(days=365*value)
    else:
        return timedelta(seconds=value)  # fallback

@router.my_chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def handle_member_join(event: ChatMemberUpdated, bot: Bot) -> None:
    """Handle a user (or bot) joining the chat."""
    try:
        if event.new_chat_member:
            if event.new_chat_member.user.id == bot.id:
                q = (
                    Chat_listModel.insert({
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
                    text="Вы добавили отвального бота себе в чат"
                )
            else:
                q = (
                    TextModel
                    .select(TextModel.text_of)
                    .where(TextModel.target == "welcome_message")
                    .first()
                )
                WELCOME_MESSAGE = q.text_of if q else "Добро пожаловать!"
                q2 = (
                    User_listModel
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
                    text=f"{WELCOME_MESSAGE}, {event.from_user.first_name}!"
                )
    except Exception as e:
        logger.error(f"Error in handle_member_join: {e}")

@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def handle_member_leave(event: ChatMemberUpdated, bot: Bot) -> None:
    """Handle a user leaving the chat."""
    try:
        q = (
            TextModel
            .select(TextModel.text_of)
            .where(TextModel.target == "bye_message")
            .first()
        )
        GOODBYE_MESSAGE = q.text_of if q else "До свидания!"
        q2 = (
            User_listModel
            .select(User_listModel.created_at, User_listModel.message_count)
            .where(User_listModel.user_id == event.from_user.id)
            .first()
        )
        if q2:
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
        else:
            await bot.send_message(
                chat_id=event.chat.id,
                text=f"{GOODBYE_MESSAGE}, {event.from_user.first_name}!\nЛегенды не вмирают"
            )
    except Exception as e:
        logger.error(f"Error in handle_member_leave: {e}")

@router.message(Command(BotCommand(command="stat", description="Вывод статистики пользователя")))
async def stat(message: Message, bot: Bot) -> None:
    """Show user statistics."""
    try:
        q = (
            User_listModel
            .select(User_listModel.created_at, User_listModel.message_count)
            .where(User_listModel.user_id == message.from_user.id)
            .first()
        )
        if q:
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
        else:
            await bot.send_message(
                chat_id=message.chat.id,
                text="Нет данных о пользователе."
            )
    except Exception as e:
        logger.error(f"Error in stat: {e}")
        await bot.send_message(
            chat_id=message.chat.id,
            text="Ошибка при получении статистики пользователя."
        )

@router.message(Command(BotCommand(command="set_welcome", description="Изменить приветственное сообщение")))
async def set_welcome(message: Message) -> None:
    """Set the welcome message."""
    try:
        if message.reply_to_message and message.reply_to_message.text:
            WELCOME_MESSAGE = message.reply_to_message.text
        elif message.text and len(message.text.split(maxsplit=1)) > 1:
            WELCOME_MESSAGE = message.text.split(maxsplit=1)[1]
        else:
            await message.reply("Приветствие не обновлено!")
            return
        q = (
            TextModel
            .update({TextModel.text_of: WELCOME_MESSAGE})
            .where(TextModel.target == "welcome_message")
        )
        q.execute()
        await message.reply("Приветствие обновлено!")
    except Exception as e:
        logger.error(f"Error in set_welcome: {e}")
        await message.reply("Приветствие не обновлено!")

@router.message(Command(BotCommand(command="set_bye", description="Изменить прощальное сообщение")))
async def set_bye(message: Message) -> None:
    """Set the goodbye message."""
    try:
        if message.reply_to_message and message.reply_to_message.text:
            GOODBYE_MESSAGE = message.reply_to_message.text
        elif message.text and len(message.text.split(maxsplit=1)) > 1:
            GOODBYE_MESSAGE = message.text.split(maxsplit=1)[1]
        else:
            await message.reply("Прощание не обновлено!")
            return
        q = (
            TextModel
            .update({TextModel.text_of: GOODBYE_MESSAGE})
            .where(TextModel.target == "bye_message")
        )
        q.execute()
        await message.reply("Прощание обновлено!")
    except Exception as e:
        logger.error(f"Error in set_bye: {e}")
        await message.reply("Прощание не обновлено!")

@router.message(Command(BotCommand(command="add_button", description="Добавить кнопку в ссылках")))
async def add_button(message: Message) -> None:
    """Add a button to the links list."""
    try:
        text = message.text.removeprefix('/add_button ').strip()
        parts = text.split('" "')
        button_name = parts[0].strip('"')
        link = parts[1].strip('"')
        q = (
            Button_listModel
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
        logger.error(f"Error in add_button: {e}")
        await message.reply("Ошибка при добавлении кнопки.")

@router.message(Command(BotCommand(command="del_button", description="Удалить кнопку в ссылках")))
async def del_button(message: Message) -> None:
    """Delete a button from the links list."""
    try:
        text = message.text.removeprefix('/del_button ').strip()
        q = Button_listModel.delete().where(Button_listModel.button_name == text)
        q.execute()
        await message.reply(f"Удалена кнопка: {text}")
    except Exception as e:
        logger.error(f"Error in del_button: {e}")
        await message.reply("Ошибка при удалении кнопки.")

@router.message(Command(BotCommand(command="rules", description="Правила")))
async def send_rules(message: Message) -> None:
    """Send the chat rules."""
    try:
        q = (
            TextModel
            .select(TextModel.text_of)
            .where(TextModel.target == "rules")
            .first()
        )
        rules = q.text_of if q else "Правила не заданы."
        await message.reply(rules)
    except Exception as e:
        logger.error(f"Error in send_rules: {e}")
        await message.reply("Ошибка при получении правил.")

@router.message(Command(BotCommand(command="links", description="Полезные ссылки")))
async def send_links(message: Message) -> None:
    """Send the list of useful links as inline buttons, including a rules button."""
    try:
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
        builder.adjust(len(link_list) + 1)
        for record in link_list:
            button_name = record["button_name"]
            button_link = record["button_link"]
            builder.button(text=button_name, url=button_link)
        # Add a rules button (link to a message in the chat)
        if message.chat.type in ("group", "supergroup"):
            chat_id = message.chat.id
            rules_url = f"https://t.me/c/{str(chat_id)[4:]}/{RULES_MESSAGE_ID}" if str(chat_id).startswith("-100") else None
            if rules_url:
                builder.button(text="Правила чата", url=rules_url)
        await message.reply("Ссылки:", reply_markup=builder.as_markup())
    except Exception as e:
        logger.error(f"Error in send_links: {e}")
        await message.reply("Ошибка при получении ссылок.")

@router.message(Command(BotCommand(command="size", description="Команда по измерению своего бубуя")))
async def measure_size(message: Message) -> None:
    """Send a random size message, save it for the user, and reset at the start of a new day."""
    try:
        user_id = message.from_user.id
        username = message.from_user.first_name or message.from_user.username
        today = datetime.now().date()
        q = (
            SizeModel
            .select(SizeModel.size, SizeModel.date)
            .where(SizeModel.user_id == user_id)
            .first()
        )
        if q and q.date == today:
            size = q.size
        else:
            size = random.randint(4, 100)
            (
                SizeModel
                .insert({
                    SizeModel.user_id: user_id,
                    SizeModel.size: size,
                    SizeModel.date: today
                })
                .on_conflict(
                    conflict_target=[SizeModel.user_id],
                    update={SizeModel.size: size, SizeModel.date: today}
                )
            ).execute()
        with open("xyz.txt", "r", encoding="utf-8") as file:
            lines = [line.strip() for line in file]
        dick_name = random.choice(lines)
        await message.reply(f"{dick_name} of {username} {size} см")
    except Exception as e:
        logger.error(f"Error in measure_size: {e}")
        await message.reply("Ошибка при измерении размера.")

@router.message(Command(BotCommand(command="anekdot", description="Внимание, АНЕКДОТ!!!")))
async def i_want_anekdot(message: Message) -> None:
    """Send a random joke if the user is within quota."""
    try:
        userId = message.from_user.id
        q2 = (
            AnekModel.select(AnekModel.count)
            .where(AnekModel.user_id == userId)
            .first()
        )
        count_qu = q2.count if q2 else 0
        if quota_check(userId, count_qu):
            try:
                anekdot = await fetch_random_joke()
                if not anekdot:
                    await message.reply("Не удалось получить анекдот. Попробуйте позже.")
                    return
                q = (
                    AnekModel
                    .insert({
                        AnekModel.created_at: fn.now(),
                        AnekModel.user_id: userId,
                        AnekModel.count: 1
                    })
                    .on_conflict(
                        conflict_target=[AnekModel.user_id],
                        preserve=[AnekModel.created_at],
                        update={AnekModel.count: AnekModel.count + 1}
                    )
                )
                q.execute()
                await message.reply(anekdot, parse_mode="markdown")
            except Exception as e:
                logger.error(f"Error fetching joke: {e}")
                await message.reply("Анекдота не будет. Системная ошибка, обратитесь к отвальному создателю")
        else:
            await message.reply("Анекдота не будет. Превышен лимит на день!")
    except Exception as e:
        logger.error(f"Error in i_want_anekdot: {e}")
        await message.reply("Ошибка при получении анекдота.")

@router.message()
async def messages_counter(message: Message, bot: Bot) -> None:
    """Count user messages for statistics."""
    try:
        q = (
            User_listModel
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
        logger.error(f"Error in messages_counter: {e}")

@router.message(Command("m"))
async def admin_mute(message: Message, bot: Bot) -> None:
    """Mute a user for a specified time or indefinitely."""
    try:
        if not message.reply_to_message:
            await message.reply("Ответьте на сообщение пользователя, чтобы замутить его.")
            return
        user_id = message.reply_to_message.from_user.id
        args = message.text.split(maxsplit=1)
        duration = None
        if len(args) > 1:
            duration = parse_time_arg(args[1])
        until_date = datetime.now() + (duration if duration else timedelta(days=365*100))
        await bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=user_id,
            permissions={"can_send_messages": False},
            until_date=until_date
        )
        time_str = f"на {args[1]}" if len(args) > 1 else "навсегда"
        await message.reply(f"{message.reply_to_message.from_user.first_name} в муте {time_str}")
    except Exception as e:
        logger.error(f"Error in admin_mute: {e}")
        await message.reply("Ошибка при муте пользователя.")

@router.message(Command("b"))
async def admin_ban(message: Message, bot: Bot) -> None:
    """Ban a user for a specified time or indefinitely."""
    try:
        if not message.reply_to_message:
            await message.reply("Ответьте на сообщение пользователя, чтобы забанить его.")
            return
        user_id = message.reply_to_message.from_user.id
        args = message.text.split(maxsplit=1)
        duration = None
        if len(args) > 1:
            duration = parse_time_arg(args[1])
        until_date = datetime.now() + (duration if duration else timedelta(days=365*100))
        await bot.ban_chat_member(
            chat_id=message.chat.id,
            user_id=user_id,
            until_date=until_date
        )
        time_str = f"на {args[1]}" if len(args) > 1 else "навсегда"
        await message.reply(f"{message.reply_to_message.from_user.first_name} забанен {time_str}")
    except Exception as e:
        logger.error(f"Error in admin_ban: {e}")
        await message.reply("Ошибка при бане пользователя.")

@router.message(F.sender_chat.type == "channel")
async def pin_only_last_channel_message(message: Message, bot: Bot) -> None:
    """Unpin all, then pin the latest channel message in the group."""
    try:
        await bot.unpin_all_chat_messages(message.chat.id)
        await bot.pin_chat_message(message.chat.id, message.message_id)
    except Exception as e:
        logger.warning(f"Failed to unpin/pin channel message: {e}")
