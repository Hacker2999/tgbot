import logging
from datetime import datetime, timedelta
import random
import re

from aiogram import Router, Bot, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated, BotCommand, MenuButtonCommands, ChatPermissions
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

RULES_MESSAGE_ID = 1  # TODO: Установите сюда реальный ID сообщения с правилами в вашем чате

def parse_time_arg(arg: str) -> timedelta:
    logger.debug(f"parse_time_arg: arg={arg}")
    match = re.match(r"(\d+)\s*(min|m|h|d|w|y|mo|mon)?", arg)
    if not match:
        logger.warning(f"parse_time_arg: не удалось распознать аргумент времени: {arg}")
        return None
    value, unit = match.groups()
    value = int(value)
    logger.debug(f"parse_time_arg: value={value}, unit={unit}")
    if unit in ("min", "m"):
        return timedelta(minutes=value)
    elif unit == "h":
        return timedelta(hours=value)
    elif unit == "d":
        return timedelta(days=value)
    elif unit == "w":
        return timedelta(weeks=value)
    elif unit in ("mo", "mon"):
        return timedelta(days=30*value)
    elif unit == "y":
        return timedelta(days=365*value)
    else:
        return timedelta(seconds=value)  # по умолчанию секунды

@router.my_chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def handle_member_join(event: ChatMemberUpdated, bot: Bot) -> None:
    logger.debug(f"handle_member_join: event={event}")
    try:
        if event.new_chat_member:
            logger.debug(f"handle_member_join: new_chat_member.id={event.new_chat_member.user.id}, bot.id={bot.id}")
            if event.new_chat_member.user.id == bot.id:
                logger.info(f"Бот добавлен в чат {event.chat.id}")
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
                logger.debug(f"handle_member_join: выполняется insert Chat_listModel для chat_id={event.chat.id}")
                q.execute()
                logger.debug(f"handle_member_join: insert Chat_listModel выполнен")
                await bot.send_message(
                    chat_id=event.chat.id,
                    text="Бот успешно добавлен в этот чат!"
                )
            else:
                logger.info(f"Пользователь {event.from_user.id} присоединился к чату {event.chat.id}")
                q = (
                    TextModel
                    .select(TextModel.text_of)
                    .where(TextModel.target == "welcome_message")
                    .first()
                )
                logger.debug(f"handle_member_join: welcome_message={q.text_of if q else None}")
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
                logger.debug(f"handle_member_join: выполняется insert User_listModel для user_id={event.from_user.id}")
                q2.execute()
                logger.debug(f"handle_member_join: insert User_listModel выполнен")
                await bot.send_message(
                    chat_id=event.chat.id,
                    text=f"{WELCOME_MESSAGE}, {event.from_user.first_name}!"
                )
        else:
            logger.warning(f"handle_member_join: event.new_chat_member отсутствует")
    except Exception as e:
        logger.error(f"Ошибка в handle_member_join: {e}")

@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def handle_user_join(event: ChatMemberUpdated, bot: Bot) -> None:
    logger.info(f"User joined: {event.new_chat_member.user.id}")
    try:
        q = (
            TextModel
            .select(TextModel.text_of)
            .where(TextModel.target == "welcome_message")
            .first()
        )
        WELCOME_MESSAGE = q.text_of if q else "Добро пожаловать!"
        await bot.send_message(
            chat_id=event.chat.id,
            text=f"{WELCOME_MESSAGE}, {event.new_chat_member.user.first_name}!"
        )
    except Exception as e:
        logger.error(f"Ошибка в handle_user_join: {e}")

@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def handle_member_leave(event: ChatMemberUpdated, bot: Bot) -> None:
    logger.debug(f"handle_member_leave: event={event}")
    try:
        q = (
            TextModel
            .select(TextModel.text_of)
            .where(TextModel.target == "bye_message")
            .first()
        )
        logger.debug(f"handle_member_leave: bye_message={q.text_of if q else None}")
        GOODBYE_MESSAGE = q.text_of if q else "До свидания!"
        q2 = (
            User_listModel
            .select(User_listModel.created_at, User_listModel.message_count)
            .where(User_listModel.user_id == event.from_user.id)
            .first()
        )
        logger.debug(f"handle_member_leave: user_stat={q2}")
        if q2:
            logger.info(f"Пользователь {event.old_chat_member.user.id} покинул чат {event.chat.id}, был с нами {q2.created_at}")
            time_withus = datetime.astimezone(datetime.now()) - q2.created_at
            days = time_withus.days
            hours = time_withus.seconds // 3600
            minutes = (time_withus.seconds % 3600) // 60
            logger.debug(f"handle_member_leave: days={days}, hours={hours}, minutes={minutes}")
            await bot.send_message(
                chat_id=event.chat.id,
                text=(
                    f"{GOODBYE_MESSAGE}, {event.old_chat_member.user.first_name}!\n"
                    f"Сообщений: {q2.message_count}\n"
                    f"Был с нами: {days} дн., {hours} ч., {minutes} мин."
                )
            )
        else:
            logger.info(f"Пользователь {event.old_chat_member.user.id} покинул чат {event.chat.id}, данных о нём нет")
            await bot.send_message(
                chat_id=event.chat.id,
                text=f"{GOODBYE_MESSAGE}, {event.old_chat_member.user.first_name}! Легенды не умирают."
            )
    except Exception as e:
        logger.error(f"Ошибка в handle_member_leave: {e}")

@router.message(Command(BotCommand(command="stat", description="Вывод статистики пользователя")))
async def stat(message: Message, bot: Bot) -> None:
    logger.debug(f"stat: user_id={message.from_user.id}, chat_id={message.chat.id}")
    try:
        q = (
            User_listModel
            .select(User_listModel.created_at, User_listModel.message_count)
            .where(User_listModel.user_id == message.from_user.id)
            .first()
        )
        if q:
            logger.info(f"Статистика для пользователя {message.from_user.id}: сообщений={q.message_count}, с {q.created_at}")
            time_withus = datetime.astimezone(datetime.now()) - q.created_at
            days = time_withus.days
            hours = time_withus.seconds // 3600
            minutes = (time_withus.seconds % 3600) // 60
            await bot.send_message(
                chat_id=message.chat.id,
                text=(
                    f"Статистика для {message.from_user.first_name}:\n"
                    f"Сообщений: {q.message_count}\n"
                    f"С нами: {days} дн., {hours} ч., {minutes} мин."
                )
            )
        else:
            logger.info(f"Нет данных о пользователе {message.from_user.id}")
            await bot.send_message(
                chat_id=message.chat.id,
                text="Нет данных о пользователе."
            )
    except Exception as e:
        logger.error(f"Ошибка в stat: {e}")
        await bot.send_message(
            chat_id=message.chat.id,
            text="Ошибка при получении статистики пользователя."
        )

@router.message(Command(BotCommand(command="set_welcome", description="Изменить приветственное сообщение")))
async def set_welcome(message: Message) -> None:
    logger.debug(f"set_welcome: user_id={message.from_user.id}, chat_id={message.chat.id}, text={message.text}")
    try:
        if message.reply_to_message and message.reply_to_message.text:
            WELCOME_MESSAGE = message.reply_to_message.text
        elif message.text and len(message.text.split(maxsplit=1)) > 1:
            WELCOME_MESSAGE = message.text.split(maxsplit=1)[1]
        else:
            logger.warning("Попытка обновить приветствие без текста")
            await message.reply("Приветствие не обновлено!")
            return
        q = (
            TextModel
            .update({TextModel.text_of: WELCOME_MESSAGE})
            .where(TextModel.target == "welcome_message")
        )
        q.execute()
        logger.info(f"Приветствие обновлено пользователем {message.from_user.id}")
        await message.reply("Приветствие обновлено!")
    except Exception as e:
        logger.error(f"Ошибка в set_welcome: {e}")
        await message.reply("Приветствие не обновлено!")

@router.message(Command(BotCommand(command="set_bye", description="Изменить прощальное сообщение")))
async def set_bye(message: Message) -> None:
    logger.debug(f"set_bye: user_id={message.from_user.id}, chat_id={message.chat.id}, text={message.text}")
    try:
        if message.reply_to_message and message.reply_to_message.text:
            GOODBYE_MESSAGE = message.reply_to_message.text
        elif message.text and len(message.text.split(maxsplit=1)) > 1:
            GOODBYE_MESSAGE = message.text.split(maxsplit=1)[1]
        else:
            logger.warning("Попытка обновить прощание без текста")
            await message.reply("Прощание не обновлено!")
            return
        q = (
            TextModel
            .update({TextModel.text_of: GOODBYE_MESSAGE})
            .where(TextModel.target == "bye_message")
        )
        q.execute()
        logger.info(f"Прощание обновлено пользователем {message.from_user.id}")
        await message.reply("Прощание обновлено!")
    except Exception as e:
        logger.error(f"Ошибка в set_bye: {e}")
        await message.reply("Прощание не обновлено!")

@router.message(Command(BotCommand(command="add_button", description="Добавить кнопку в ссылках")))
async def add_button(message: Message) -> None:
    logger.debug(f"add_button: user_id={message.from_user.id}, chat_id={message.chat.id}, text={message.text}")
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
        logger.info(f"Добавлена кнопка: {button_name} пользователем {message.from_user.id}")
        await message.reply(f"Добавлена кнопка: {button_name}")
    except Exception as e:
        logger.error(f"Ошибка в add_button: {e}")
        await message.reply("Ошибка при добавлении кнопки.")

@router.message(Command(BotCommand(command="del_button", description="Удалить кнопку в ссылках")))
async def del_button(message: Message) -> None:
    logger.debug(f"del_button: user_id={message.from_user.id}, chat_id={message.chat.id}, text={message.text}")
    try:
        text = message.text.removeprefix('/del_button ').strip()
        q = Button_listModel.delete().where(Button_listModel.button_name == text)
        q.execute()
        logger.info(f"Удалена кнопка: {text} пользователем {message.from_user.id}")
        await message.reply(f"Удалена кнопка: {text}")
    except Exception as e:
        logger.error(f"Ошибка в del_button: {e}")
        await message.reply("Ошибка при удалении кнопки.")

@router.message(Command(BotCommand(command="rules", description="Правила")))
async def send_rules(message: Message) -> None:
    logger.debug(f"send_rules: user_id={message.from_user.id}, chat_id={message.chat.id}")
    try:
        q = (
            TextModel
            .select(TextModel.text_of)
            .where(TextModel.target == "rules")
            .first()
        )
        rules = q.text_of if q else "Правила не заданы."
        logger.info(f"Отправлены правила пользователю {message.from_user.id}")
        await message.reply(rules)
    except Exception as e:
        logger.error(f"Ошибка в send_rules: {e}")
        await message.reply("Ошибка при получении правил.")

@router.message(Command(BotCommand(command="links", description="Полезные ссылки")))
async def send_links(message: Message) -> None:
    logger.debug(f"send_links: user_id={message.from_user.id}, chat_id={message.chat.id}")
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
        logger.info(f"Отправлены ссылки пользователю {message.from_user.id}")
        await message.reply("Ссылки:", reply_markup=builder.as_markup())
    except Exception as e:
        logger.error(f"Ошибка в send_links: {e}")
        await message.reply("Ошибка при получении ссылок.")

@router.message(Command(BotCommand(command="size", description="Команда по измерению своего бубуя")))
async def measure_size(message: Message) -> None:
    logger.debug(f"measure_size: user_id={message.from_user.id}, chat_id={message.chat.id}")
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
            logger.info(f"Пользователь {user_id} уже измерял размер сегодня: {size}")
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
            logger.info(f"Пользователь {user_id} получил новый размер: {size}")
        with open("xyz.txt", "r", encoding="utf-8") as file:
            lines = [line.strip() for line in file]
        dick_name = random.choice(lines)
        await message.reply(f"{dick_name} {username}: {size} см")
    except Exception as e:
        logger.error(f"Ошибка в measure_size: {e}")
        await message.reply("Ошибка при измерении размера.")

@router.message(Command(BotCommand(command="anekdot", description="Внимание, АНЕКДОТ!!!")))
async def i_want_anekdot(message: Message) -> None:
    logger.debug(f"i_want_anekdot: user_id={message.from_user.id}, chat_id={message.chat.id}")
    try:
        userId = message.from_user.id
        q2 = (
            AnekModel.select(AnekModel.count)
            .where(AnekModel.user_id == userId)
            .first()
        )
        count_qu = q2.count if q2 else 0
        logger.info(f"Пользователь {userId} запросил анекдот, count_qu={count_qu}")
        if quota_check(userId, count_qu):
            try:
                anekdot = await fetch_random_joke()
                if not anekdot:
                    logger.warning(f"Не удалось получить анекдот для пользователя {userId}")
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
                logger.info(f"Анекдот отправлен пользователю {userId}")
                await message.reply(anekdot, parse_mode="markdown")
            except Exception as e:
                logger.error(f"Ошибка при получении анекдота: {e}")
                await message.reply("Анекдота не будет. Системная ошибка, обратитесь к администратору.")
        else:
            logger.info(f"Пользователь {userId} превысил лимит анекдотов")
            await message.reply("Анекдота не будет. Превышен лимит на день!")
    except Exception as e:
        logger.error(f"Ошибка в i_want_anekdot: {e}")
        await message.reply("Ошибка при получении анекдота.")

@router.message(Command("size_top"))
async def size_top(message: Message, bot: Bot) -> None:
    from datetime import datetime
    today = datetime.now().date()
    # Получаем все замеры за сегодня
    query = (
        SizeModel
        .select(SizeModel.user_id, SizeModel.size)
        .where(SizeModel.date == today)
        .order_by(SizeModel.size.desc())
    )
    results = list(query)
    if not results:
        await message.reply("Сегодня ещё никто не измерял размер!")
        return

    # Эмодзи для топ-3
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for idx, row in enumerate(results, 1):
        try:
            user = await bot.get_chat_member(message.chat.id, row.user_id)
            name = user.user.first_name
        except Exception:
            name = f"ID {row.user_id}"
        medal = medals[idx-1] if idx <= 3 else f"{idx}."
        lines.append(f"{medal} <b>{name}</b> — <b>{row.size} см</b>")

    text = "<b>🏆 Турнирная таблица размеров за сегодня:</b>\n\n" + "\n".join(lines)
    await message.reply(text, parse_mode="HTML")

async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    member = await bot.get_chat_member(chat_id, user_id)
    logger.info("is_admin check:", user_id, member.status)
    return member.status in ("administrator", "creator")

@router.message(Command("m"))
async def admin_mute(message: Message, bot: Bot) -> None:
    logger.debug(f"admin_mute: user_id={message.from_user.id}, chat_id={message.chat.id}, text={message.text}")
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        logger.warning(f"Пользователь {message.from_user.id} попытался использовать /m без прав администратора")
        await message.reply("Только администратор может использовать эту команду.")
        return
    try:
        if not message.reply_to_message:
            logger.warning(f"/m без ответа на сообщение, user_id={message.from_user.id}")
            await message.reply("Ответьте на сообщение пользователя, чтобы замутить его.")
            return
        user_id = message.reply_to_message.from_user.id
        admin_name = message.from_user.first_name
        muted_name = message.reply_to_message.from_user.first_name
        args = message.text.split(maxsplit=1)
        duration = None
        if len(args) > 1:
            duration = parse_time_arg(args[1])
        until_date = datetime.now() + (duration if duration else timedelta(days=365*100))
        await bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_date
        )
        time_str = f"на {args[1]}" if len(args) > 1 else "навсегда"
        logger.info(f"Пользователь {user_id} замучен админом {message.from_user.id} {time_str}")
        unmute_time = until_date.strftime('%d.%m.%Y %H:%M') if duration else '∞'
        await message.reply(
            f"Пользователь <b>{muted_name}</b> (id: <code>{user_id}</code>) был замучен админом <b>{admin_name}</b> (id: <code>{message.from_user.id}</code>) {time_str}.\n"
            f"Размут: <b>{unmute_time}</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка в admin_mute: {e}")
        await message.reply("Ошибка при муте пользователя.")

@router.message(Command("b"))
async def admin_ban(message: Message, bot: Bot) -> None:
    logger.debug(f"admin_ban: user_id={message.from_user.id}, chat_id={message.chat.id}, text={message.text}")
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        logger.warning(f"Пользователь {message.from_user.id} попытался использовать /b без прав администратора")
        await message.reply("Только администратор может использовать эту команду.")
        return
    try:
        if not message.reply_to_message:
            logger.warning(f"/b без ответа на сообщение, user_id={message.from_user.id}")
            await message.reply("Ответьте на сообщение пользователя, чтобы забанить его.")
            return
        user_id = message.reply_to_message.from_user.id
        admin_name = message.from_user.first_name
        banned_name = message.reply_to_message.from_user.first_name
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
        logger.info(f"Пользователь {user_id} забанен админом {message.from_user.id} {time_str}")
        unban_time = until_date.strftime('%d.%m.%Y %H:%M') if duration else '∞'
        await message.reply(
            f"Пользователь <b>{banned_name}</b> (id: <code>{user_id}</code>) был забанен админом <b>{admin_name}</b> (id: <code>{message.from_user.id}</code>) {time_str}.\n"
            f"Разбан: <b>{unban_time}</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка в admin_ban: {e}")
        await message.reply("Ошибка при бане пользователя.")

@router.message()
async def messages_counter(message: Message, bot: Bot) -> None:
    logger.debug(f"messages_counter: user_id={message.from_user.id}, chat_id={message.chat.id}")
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
        logger.info(f"Сообщение пользователя {message.from_user.id} учтено в статистике")
    except Exception as e:
        logger.error(f"Ошибка в messages_counter: {e}")

@router.message(F.sender_chat.type == "channel")
async def pin_only_last_channel_message(message: Message, bot: Bot) -> None:
    logger.debug(f"pin_only_last_channel_message: chat_id={message.chat.id}, message_id={message.message_id}")
    try:
        await bot.unpin_all_chat_messages(message.chat.id)
        await bot.pin_chat_message(message.chat.id, message.message_id)
        logger.info(f"Закреплено сообщение {message.message_id} в чате {message.chat.id}")
    except Exception as e:
        logger.warning(f"Не удалось закрепить сообщение канала: {e}")
