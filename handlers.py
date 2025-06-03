import logging
from datetime import datetime, timedelta
import random
import re
import asyncio
import hashlib

from aiogram import Router, Bot, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated, BotCommand, MenuButtonCommands, ChatPermissions, CallbackQuery
from aiogram.filters import Command, ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from aiogram.utils.keyboard import InlineKeyboardBuilder
from peewee import fn

from baneks_api import fetch_random_joke
from model import TextModel, AnekModel, User_listModel, Chat_listModel, Button_listModel, SizeModel
from utils import quota_check
from config import RULES, API_TOKEN, SPAM_LIMIT, DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT

router = Router()
logger = logging.getLogger(__name__)


# --- Вспомогательные функции ---
def parse_time_arg(arg: str) -> timedelta:
    match = re.match(r"(\d+)\s*(min|m|h|d|w|y|mo|mon)?", arg)
    if not match:
        return None
    value, unit = match.groups()
    value = int(value)
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
        return timedelta(seconds=value)

# --- Обработчики событий ---

@router.my_chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def handle_member_join(event: ChatMemberUpdated, bot: Bot) -> None:
    try:
        if event.new_chat_member and event.new_chat_member.user.id == bot.id:
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
                text="Бот успешно добавлен в этот чат!"
            )
    except Exception as e:
        logger.error(f"Ошибка в handle_member_join: {e}")

# --- Анти-рейд капча ---

CAPTCHA_TIMEOUT = 120  # секунд
CAPTCHA_ANSWERS = ["Я не бот", "Я бот", "12345"]

@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def handle_user_join(event: ChatMemberUpdated, bot: Bot) -> None:
    try:
        user_id = event.new_chat_member.user.id
        chat_id = event.chat.id
        # 1. Ограничить права пользователя (только чтение)
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(can_send_messages=False)
        )
        # 2. Сгенерировать капчу
        answers = CAPTCHA_ANSWERS.copy()
        random.shuffle(answers)
        correct = "Я не бот"
        builder = InlineKeyboardBuilder()
        for ans in answers:
            builder.button(text=ans, callback_data=f"captcha_{ans}_{user_id}")
        markup = builder.as_markup()
        # 3. Отправить капчу
        captcha_msg = await bot.send_message(
            chat_id=chat_id,
            text=f"<b>Привет, {event.new_chat_member.user.first_name}!</b>\nПодтвердите, что вы не бот, нажав на правильную кнопку ниже. У вас 2 минуты.",
            reply_markup=markup,
            parse_mode="HTML"
        )
        # 4. Ждать прохождения капчи
        async def captcha_timeout():
            await asyncio.sleep(CAPTCHA_TIMEOUT)
            # Проверить, сняты ли ограничения
            member = await bot.get_chat_member(chat_id, user_id)
            # Проверяем статус и права
            if getattr(member, 'status', None) == 'restricted' and getattr(member, 'can_send_messages', True) is False:
                try:
                    await bot.ban_chat_member(chat_id, user_id)
                    await bot.unban_chat_member(chat_id, user_id)  # кик
                    await bot.send_message(chat_id, f"Пользователь {event.new_chat_member.user.first_name} не прошёл капчу и был удалён.")
                except Exception as e:
                    logger.error(f"Ошибка при кике за не пройденную капчу: {e}")
        asyncio.create_task(captcha_timeout())
    except Exception as e:
        logger.error(f"Ошибка в handle_user_join (captcha): {e}")

@router.callback_query(F.data.startswith("captcha_"))
async def captcha_callback(call: CallbackQuery, bot: Bot) -> None:
    try:
        data = call.data.split("_")
        answer = data[1]
        user_id = int(data[2])
        if call.from_user.id != user_id:
            await call.answer("Это не ваша капча!", show_alert=True)
            return
        chat_id = call.message.chat.id
        if answer == "Я не бот":
            # Снять ограничения
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True)
            )
            await call.message.edit_text("✅ Капча пройдена! Добро пожаловать!")
            # Отправить приветственное сообщение из базы
            q = (
                TextModel
                .select(TextModel.text_of)
                .where(TextModel.target == "welcome_message")
                .first()
            )
            WELCOME_MESSAGE = q.text_of if q else "Добро пожаловать!"
            await bot.send_message(
                chat_id=chat_id,
                text=f"{WELCOME_MESSAGE}, {call.from_user.first_name}!"
            )
        else:
            await call.answer("Неверно! Попробуйте ещё раз.", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка в captcha_callback: {e}")

@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def handle_member_leave(event: ChatMemberUpdated, bot: Bot) -> None:
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
            .where(User_listModel.user_id == event.old_chat_member.user.id)
            .first()
        )
        if q2:
            time_withus = datetime.astimezone(datetime.now()) - q2.created_at
            days = time_withus.days
            hours = time_withus.seconds // 3600
            minutes = (time_withus.seconds % 3600) // 60
            await bot.send_message(
                chat_id=event.chat.id,
                text=(
                    f"{GOODBYE_MESSAGE}, {event.old_chat_member.user.first_name}!\n"
                    f"Сообщений: {q2.message_count}\n"
                    f"Был с нами: {days} дн., {hours} ч., {minutes} мин."
                )
            )
        else:
            await bot.send_message(
                chat_id=event.chat.id,
                text=f"{GOODBYE_MESSAGE}, {event.old_chat_member.user.first_name}! Легенды не умирают."
            )
    except Exception as e:
        logger.error(f"Ошибка в handle_member_leave: {e}")

# --- Команды пользователей и админов ---

@router.message(Command("stat"))
async def stat(message: Message, bot: Bot) -> None:
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
                text=(
                    f"Статистика для {message.from_user.first_name}:\n"
                    f"Сообщений: {q.message_count}\n"
                    f"С нами: {days} дн., {hours} ч., {minutes} мин."
                )
            )
        else:
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

@router.message(Command("set_welcome"))
async def set_welcome(message: Message, bot: Bot) -> None:
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Только администратор может использовать эту команду.")
        return
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
        logger.error(f"Ошибка в set_welcome: {e}")
        await message.reply("Приветствие не обновлено!")

@router.message(Command("set_bye"))
async def set_bye(message: Message, bot: Bot) -> None:
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Только администратор может использовать эту команду.")
        return
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
        logger.error(f"Ошибка в set_bye: {e}")
        await message.reply("Прощание не обновлено!")

@router.message(Command("add_button"))
async def add_button(message: Message, bot: Bot) -> None:
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Только администратор может использовать эту команду.")
        return
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
        logger.error(f"Ошибка в add_button: {e}")
        await message.reply("Ошибка при добавлении кнопки.")

@router.message(Command("del_button"))
async def del_button(message: Message, bot: Bot) -> None:
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Только администратор может использовать эту команду.")
        return
    try:
        text = message.text.removeprefix('/del_button ').strip()
        q = Button_listModel.delete().where(Button_listModel.button_name == text)
        q.execute()
        await message.reply(f"Удалена кнопка: {text}")
    except Exception as e:
        logger.error(f"Ошибка в del_button: {e}")
        await message.reply("Ошибка при удалении кнопки.")

@router.message(Command("rules"))
async def send_rules(message: Message) -> None:
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
        logger.error(f"Ошибка в send_rules: {e}")
        await message.reply("Ошибка при получении правил.")

@router.message(Command("links"))
async def send_links(message: Message) -> None:
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
        await message.reply("Ссылки:", reply_markup=builder.as_markup())
    except Exception as e:
        logger.error(f"Ошибка в send_links: {e}")
        await message.reply("Ошибка при получении ссылок.")

@router.message(Command("size"))
async def measure_size(message: Message) -> None:
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
            # Удача: хэш от user_id и даты, нормализуем в диапазон 0..1
            luck_seed = f"{user_id}_{today}".encode()
            luck_hash = hashlib.sha256(luck_seed).hexdigest()
            luck = int(luck_hash[:8], 16) / 0xFFFFFFFF
            # Новый диапазон: 5..50
            base = 5
            max_size = 50
            random_part = random.randint(0, 5)
            size = int(base + (max_size - base) * luck + random_part)
            if size > max_size:
                size = max_size
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
        await message.reply(f"{dick_name} {username}: {size} см")
    except Exception as e:
        logger.error(f"Ошибка в measure_size: {e}")
        await message.reply("Ошибка при измерении размера.")

@router.message(Command("size_top"))
async def size_top(message: Message, bot: Bot) -> None:
    today = datetime.now().date()
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

@router.message(Command("anekdot"))
async def i_want_anekdot(message: Message) -> None:
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
                logger.error(f"Ошибка при получении анекдота: {e}")
                await message.reply("Анекдота не будет. Системная ошибка, обратитесь к администратору.")
        else:
            await message.reply("Анекдота не будет. Превышен лимит на день!")
    except Exception as e:
        logger.error(f"Ошибка в i_want_anekdot: {e}")
        await message.reply("Ошибка при получении анекдота.")

# --- Админ-команды ---

async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    member = await bot.get_chat_member(chat_id, user_id)
    return member.status in ("administrator", "creator")

@router.message(Command("m"))
async def admin_mute(message: Message, bot: Bot) -> None:
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Только администратор может использовать эту команду.")
        return
    try:
        if not message.reply_to_message:
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
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Только администратор может использовать эту команду.")
        return
    try:
        if not message.reply_to_message:
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
        unban_time = until_date.strftime('%d.%m.%Y %H:%M') if duration else '∞'
        await message.reply(
            f"Пользователь <b>{banned_name}</b> (id: <code>{user_id}</code>) был забанен админом <b>{admin_name}</b> (id: <code>{message.from_user.id}</code>) {time_str}.\n"
            f"Разбан: <b>{unban_time}</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка в admin_ban: {e}")
        await message.reply("Ошибка при бане пользователя.")

# --- Системные обработчики ---

@router.message()
async def messages_counter(message: Message, bot: Bot) -> None:
    # Фильтруем команды (сообщения, начинающиеся с "/") и удаляем их
    if message.text and message.text.startswith("/"):
        try:
            await message.delete()
        except Exception as e:
            logger.error(f"Не удалось удалить мусорное сообщение: {e}")
        return
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
        logger.error(f"Ошибка в messages_counter: {e}")

@router.message(F.sender_chat.type == "channel")
async def pin_only_last_channel_message(message: Message, bot: Bot) -> None:
    try:
        await bot.unpin_all_chat_messages(message.chat.id)
        await bot.pin_chat_message(message.chat.id, message.message_id)
    except Exception as e:
        logger.warning(f"Не удалось закрепить сообщение канала: {e}")
