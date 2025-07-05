import logging
from datetime import datetime, timedelta, timezone
import random
import re
import asyncio
import hashlib
from typing import Optional, Dict, List, Tuple
from functools import lru_cache

from aiogram import Router, Bot, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated, BotCommand, MenuButtonCommands, ChatPermissions, CallbackQuery
from aiogram.filters import Command, ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from aiogram.utils.keyboard import InlineKeyboardBuilder
from peewee import fn, DatabaseError

from baneks_api import fetch_random_joke
from model import TextModel, AnekModel, User_listModel, Chat_listModel, Button_listModel, SizeModel
from utils import quota_check, calculate_level, calculate_exp_for_level, calculate_messages_for_level, get_user_rank, check_visit_streak, is_admin, award_exp_and_check_level_up
from config import RULES, API_TOKEN, SPAM_LIMIT, DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, KILL_CHAT_PASSWORD
from burmalda import burmalda_game, GAME_COST, ATTEMPT_REWARDS, WARN_REMOVAL_COST, VICTORY_BONUS_EXP, GAME_ATTEMPTS

router = Router()
logger = logging.getLogger(__name__)

# Константы
CAPTCHA_TIMEOUT = 120  # секунд
CAPTCHA_ANSWERS = ["Я не бот", "Я бот", "12345"]
MAX_MUTE_MINUTES = 1440  # 24 часа
MIN_MUTE_MINUTES = 1

# --- Поддерживаемые emoji для send_dice ---
SUPPORTED_DICE_EMOJI = {"🎲", "🎯", "🏀", "⚽", "🎰", "🎳"}

# --- Вспомогательные функции ---

@lru_cache(maxsize=1000)
def parse_time_arg(arg: str) -> Optional[timedelta]:
    """
    Парсит строку с временным интервалом.
    
    Args:
        arg (str): Строка с временным интервалом (например, "5m", "1h", "2d")
        
    Returns:
        Optional[timedelta]: Объект timedelta или None при ошибке
    """
    try:
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
    except Exception as e:
        logger.error(f"Ошибка при парсинге временного интервала '{arg}': {e}")
        return None


@router.my_chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def handle_member_join(event: ChatMemberUpdated, bot: Bot) -> None:
    """Обработчик добавления бота в чат."""
    try:
        if event.new_chat_member and event.new_chat_member.user.id == bot.id:
            q = (
                Chat_listModel.insert({
                    Chat_listModel.created_at: fn.now(),
                    Chat_listModel.chat_id: event.chat.id
                })
                .on_conflict(
                    conflict_target=[Chat_listModel.chat_id],
                    update={}  # Не обновляем created_at
                )
            )
            q.execute()
            await bot.send_message(
                chat_id=event.chat.id,
                text="Бот успешно добавлен в этот чат!"
            )
    except Exception as e:
        logger.error(f"Ошибка в handle_member_join для чата {event.chat.id}: {e}")

# --- Анти-рейд капча ---

@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def handle_user_join(event: ChatMemberUpdated, bot: Bot) -> None:
    try:
        user_id = event.new_chat_member.user.id
        chat_id = event.chat.id

        invite_link = getattr(event, "invite_link", None)
        username = event.new_chat_member.user.username if event.new_chat_member.user.username is not None else event.new_chat_member.user.first_name
        # Логируем вход по ссылке
        if invite_link is not None:
            logger.info(f"User {user_id} joined via invite link: {invite_link.invite_link}")
            q = (
                TextModel
                .select(TextModel.text_of)
                .where(TextModel.target == "welcome_message")
                .first()
            )
            WELCOME_MESSAGE = q.text_of if q else "Добро пожаловать!"
            username = event.from_user.username if event.from_user.username is not None else event.from_user.first_name
            await bot.send_message(
                chat_id=chat_id,
                text=f"{username}, {WELCOME_MESSAGE}!"
            )


        # Проверяем, был ли пользователь уже в чате (например, вернулся после выхода)
        member = await bot.get_chat_member(chat_id, user_id)
        if getattr(member, 'status', None) not in ("left", "kicked"):
            (
                User_listModel
                .insert({
                    User_listModel.created_at: fn.now(),
                    User_listModel.user_id: user_id,
                    User_listModel.is_verified: True,
                    User_listModel.last_visit: fn.now(),
                })
                .on_conflict(
                    conflict_target=[User_listModel.user_id],
                    update={User_listModel.is_verified: True, User_listModel.last_visit: fn.now()}
                )
            ).execute()
            return  # Не показываем капчу
        # 1. Обновить/создать запись пользователя с is_verified=False
        (
            User_listModel
            .insert({
                User_listModel.created_at: fn.now(),
                User_listModel.user_id: user_id,
                User_listModel.is_verified: False,
                User_listModel.last_visit: fn.now(),
                User_listModel.rank: 1,  # Начальный уровень
            })
            .on_conflict(
                conflict_target=[User_listModel.user_id],
                update={User_listModel.is_verified: False, User_listModel.last_visit: fn.now()}
            )
        ).execute()
        # 2. Ограничить права пользователя (только чтение)
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(can_send_messages=False)
        )
        # 3. Сгенерировать капчу
        answers = CAPTCHA_ANSWERS.copy()
        random.shuffle(answers)
        builder = InlineKeyboardBuilder()
        for ans in answers:
            builder.button(text=ans, callback_data=f"captcha_{ans}_{user_id}")
        markup = builder.as_markup()
        # 4. Отправить капчу с учётом invite_link
        welcome_text = f"<b>Привет, {username}!</b>\nПодтвердите, что вы не бот, нажав на правильную кнопку ниже. У вас 2 минуты."
        if invite_link is not None:
            welcome_text += f"\nВы зашли по ссылке-приглашению: {invite_link.invite_link}"
        captcha_msg = await bot.send_message(
            chat_id=chat_id,
            text=welcome_text,
            reply_markup=markup,
            parse_mode="HTML"
        )
        # 5. Ждать прохождения капчи
        async def captcha_timeout():
            await asyncio.sleep(CAPTCHA_TIMEOUT)
            # Проверить статус верификации
            user = User_listModel.select(User_listModel.is_verified).where(User_listModel.user_id == user_id).first()
            if not user or not user.is_verified:
                try:
                    await bot.ban_chat_member(chat_id, user_id)
                    await bot.unban_chat_member(chat_id, user_id)  # кик
                    await bot.send_message(chat_id, f"Пользователь {username} не прошёл капчу и был удалён.")
                except Exception as e:
                    logger.error(f"Ошибка при кике за не пройденную капчу: {e}")
        asyncio.create_task(captcha_timeout())
    except Exception as e:
        logger.error(f"Ошибка в handle_user_join (captcha): {e}")

@router.callback_query(F.data.startswith("captcha_"))
async def captcha_callback(call: CallbackQuery, bot: Bot) -> None:
    try:
        data = call.data.split("_")
        if len(data) != 3:
            logger.error(f"Неверный формат callback данных: {call.data}")
            await call.answer("Произошла ошибка. Попробуйте еще раз.", show_alert=True)
            return

        answer = data[1]
        try:
            user_id = int(data[2])
        except ValueError:
            logger.error(f"Неверный формат user_id в callback: {data[2]}")
            await call.answer("Произошла ошибка. Попробуйте еще раз.", show_alert=True)
            return

        if call.from_user.id != user_id:
            await call.answer("Это не ваша капча!", show_alert=True)
            return

        chat_id = call.message.chat.id
        if answer == "Я не бот":
            try:
                # Снять ограничения
                await bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_media_messages=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True
                    )
                )
                # Обновить is_verified=True
                try:
                    User_listModel.update({User_listModel.is_verified: True}).where(
                        User_listModel.user_id == user_id
                    ).execute()
                except DatabaseError as db_err:
                    logger.error(f"Ошибка при обновлении статуса верификации в БД: {db_err}")
                    await call.answer("Произошла ошибка. Попробуйте еще раз.", show_alert=True)
                    return

                await call.message.edit_text("✅ Капча пройдена! Добро пожаловать!")
                
                # Отправить приветственное сообщение из базы
                try:
                    q = (
                        TextModel
                        .select(TextModel.text_of)
                        .where(TextModel.target == "welcome_message")
                        .first()
                    )
                    WELCOME_MESSAGE = q.text_of if q else "Добро пожаловать!"
                    username = call.from_user.username if call.from_user.username is not None else call.from_user.first_name
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"{username}, {WELCOME_MESSAGE}!"
                    )
                except DatabaseError as db_err:
                    logger.error(f"Ошибка при получении приветственного сообщения из БД: {db_err}")
                    # Отправляем стандартное приветствие в случае ошибки
                    username = call.from_user.username if call.from_user.username is not None else call.from_user.first_name
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"{username}, Добро пожаловать!"
                    )
            except Exception as e:
                logger.error(f"Ошибка при обработке успешной капчи: {e}")
                await call.answer("Произошла ошибка. Попробуйте еще раз.", show_alert=True)
        else:
            await call.answer("Неверно! Попробуйте ещё раз.", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка в captcha_callback: {e}")
        await call.answer("Произошла ошибка. Попробуйте еще раз.", show_alert=True)

@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def handle_member_leave(event: ChatMemberUpdated, bot: Bot) -> None:
    try:
        username = event.old_chat_member.user.username if event.old_chat_member.user.username is not None else event.old_chat_member.user.first_name
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
                    f"{username}, {GOODBYE_MESSAGE}\n"
                    f"Сообщений: {q2.message_count}\n"
                    f"Был с нами: {days} дн., {hours} ч., {minutes} мин."
                )
            )
        else:
            await bot.send_message(
                chat_id=event.chat.id,
                text=f"{username}, {GOODBYE_MESSAGE}"
            )
    except Exception as e:
        logger.error(f"Ошибка в handle_member_leave: {e}")

# --- Команды пользователей и админов ---

@router.message(Command("stat"))
async def stat(message: Message, bot: Bot) -> None:
    try:
        # Отсеиваем привязанный канал и сообщения бота
        if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
            await message.reply("Команды нельзя использовать от имени канала.")
            return
        q = (
            User_listModel
            .select(User_listModel.created_at, User_listModel.message_count, User_listModel.level_exp, User_listModel.bonus_exp, User_listModel.credits)
            .where(User_listModel.user_id == message.from_user.id)
            .first()
        )
        if q:
            time_withus = datetime.astimezone(datetime.now()) - q.created_at
            days = time_withus.days
            hours = time_withus.seconds // 3600
            minutes = (time_withus.seconds % 3600) // 60
            username = message.from_user.username if message.from_user.username is not None else message.from_user.first_name
            
            total_exp = q.level_exp + q.bonus_exp
            current_level = calculate_level(total_exp)
            user_rank = get_user_rank(current_level)
            
            await bot.send_message(
                chat_id=message.chat.id,
                text=(
                    f"📊 <b>Статистика {username}</b>\n\n"
                    f"💬 Сообщений: <b>{q.message_count}</b>\n"
                    f"⏰ С нами: <b>{days} дн., {hours} ч., {minutes} мин.</b>\n"
                    f"📈 Уровень: <b>{current_level}</b>\n"
                    f"🏅 Звание: <b>{user_rank}</b>\n"
                    f"⭐ Общий опыт: <b>{total_exp}</b>\n"
                    f"💰 Отвальчики: <b>{q.credits}</b>"
                ),
                parse_mode="HTML"
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
            text="Ошибка при получении статистики."
        )

@router.message(Command("set_welcome"))
async def set_welcome(message: Message, bot: Bot) -> None:
    # Отсеиваем привязанный канал и сообщения бота
    if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
        return
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
    # Отсеиваем привязанный канал и сообщения бота
    if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
        return
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
    # Отсеиваем привязанный канал и сообщения бота
    if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
        return
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Только администратор может использовать эту команду.")
        return
    try:
        text = re.sub(r'^/add_button\S*\s', '', message.text).strip()
        parts = text.split(' - ')
        button_name = parts[0]
        link = parts[1]
        if link.startswith("https://"):
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
        else:
            await message.reply("Ошибка при добавлении кнопки. Неправильный формат ссылки")
            return
        await message.reply(f"Добавлена кнопка: {button_name}")
    except Exception as e:
        logger.error(f"Ошибка в add_button: {e}")
        await message.reply("Ошибка при добавлении кнопки.")

@router.message(Command("del_button"))
async def del_button(message: Message, bot: Bot) -> None:
    # Отсеиваем привязанный канал и сообщения бота
    if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
        return
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Только администратор может использовать эту команду.")
        return
    try:
        text = re.sub(r'^/del_button\S*\s', '', message.text).strip()
        q = Button_listModel.delete().where(Button_listModel.button_name == text)
        q.execute()
        await message.reply(f"Удалена кнопка: {text}")
    except Exception as e:
        logger.error(f"Ошибка в del_button: {e}")
        await message.reply("Ошибка при удалении кнопки.")

@router.message(Command("add_rules"))
async def add_rules(message: Message, bot: Bot) -> None:
    # Отсеиваем привязанный канал и сообщения бота
    if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
        return
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Только администратор может использовать эту команду.")
        return
    try:
        if message.reply_to_message and message.reply_to_message.text:
            rules_text = message.reply_to_message.text
        else:
            await message.reply("Ответьте на сообщение с текстом правил.")
            return
        from model import TextModel
        # Обновить или вставить правила
        q = (
            TextModel
            .insert({
                TextModel.target: "rules",
                TextModel.text_of: rules_text,
                TextModel.edited_at: fn.now()
            })
            .on_conflict(
                conflict_target=[TextModel.target],
                update={TextModel.text_of: rules_text, TextModel.edited_at: fn.now()}
            )
        )
        q.execute()
        await message.reply("Правила успешно обновлены!")
    except Exception as e:
        logger.error(f"Ошибка в add_rules: {e}")
        await message.reply("Ошибка при сохранении правил.")

@router.message(Command("rules"))
async def send_rules(message: Message) -> None:
    try:
        # Отсеиваем привязанный канал и сообщения бота
        if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
            await message.reply("Команды нельзя использовать от имени канала.")
            return
        from model import TextModel
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
        # Отсеиваем привязанный канал и сообщения бота
        if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
            await message.reply("Команды нельзя использовать от имени канала.")
            return
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
            builder.adjust(1)
        await message.reply("Ссылки:", reply_markup=builder.as_markup())
    except Exception as e:
        logger.error(f"Ошибка в send_links: {e}")
        await message.reply("Ошибка при получении ссылок.")

@router.message(Command("size"))
async def measure_size(message: Message) -> None:
    try:
        # Отсеиваем привязанный канал и сообщения бота
        if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
            await message.reply("Команды нельзя использовать от имени канала.")
            return
        user_id = message.from_user.id
        username = message.from_user.username if message.from_user.username is not None else message.from_user.first_name
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
    # Отсеиваем привязанный канал и сообщения бота
    if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
        return
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
            name = user.user.username if user.user.username is not None else user.user.first_name
        except Exception:
            name = f"ID {row.user_id}"
        medal = medals[idx-1] if idx <= 3 else f"  {idx}."
        lines.append(f"{medal} <b>{name}</b> — <b>{row.size} см</b>")
    text = "<b>🏆 Турнирная таблица размеров за сегодня:</b>\n\n" + "\n".join(lines)
    await message.reply(text, parse_mode="HTML")

@router.message(Command("anekdot"))
async def i_want_anekdot(message: Message) -> None:
    try:
        # Отсеиваем привязанный канал и сообщения бота
        if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
            await message.reply("Команды нельзя использовать от имени канала.")
            return
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

@router.message(Command("roulette"))
async def roulette(message: Message, bot: Bot) -> None:
    try:
        # Отсеиваем привязанный канал и сообщения бота
        if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
            await message.reply("Команды нельзя использовать от имени канала.")
            return
        # Эта команда не трогает поле is_verified, только мутит пользователя
        # Парсим ставку (минуты мута)
        args = message.text.split()
        if len(args) < 2 or not args[1].isdigit():
            await message.reply("Использование: /roulette <минуты мута>")
            return
        mute_minutes = int(args[1])
        if mute_minutes < 1 or mute_minutes > 1440:
            await message.reply("Укажите количество минут от 1 до 1440.")
            return
        # 1. Бот выбирает условие (больше или меньше)
        condition = random.choice(["больше", "меньше"])
        border = random.randint(2, 5)  # 2-5, чтобы не было слишком просто
        await message.reply(f"Если выпадет {condition} {border}, то победа 🎲\nКидаем кубик...")
        # 2. Кидаем кубик (анимированный)
        dice_msg = await bot.send_dice(message.chat.id, emoji="🎲")
        dice_value = dice_msg.dice.value  # 1-6
        # 3. Проверяем результат
        win = (dice_value > border) if condition == "больше" else (dice_value < border)
        if win:
            # Начисляем бонусный опыт
            bonus_exp = 20 * mute_minutes
            if not await is_admin(bot, message.chat.id, message.from_user.id):
                bonus_exp = 20 * mute_minutes
                if bonus_exp > 500:
                    bonus_exp = 500
            else:
                bonus_exp = 20
            user = User_listModel.get_or_none(User_listModel.user_id == message.from_user.id)
            if not user :
                (
                    User_listModel
                    .insert({
                    User_listModel.created_at: fn.now(),
                    User_listModel.user_id: message.from_user.id,
                    User_listModel.bonus_exp: bonus_exp,
                    User_listModel.last_visit: fn.now(),
                    User_listModel.rank: 1,  # Начальный уровень
                        User_listModel.credits: 0,  # Начальные отвальчики
                    })
                ).execute()
            else:
                username = message.from_user.username if message.from_user.username is not None else message.from_user.first_name
                await award_exp_and_check_level_up(message.from_user.id, 0, bonus_exp, username, message, bot)
            await message.reply(f"Победа за вами! 🎉\nВы получаете <b>{bonus_exp}</b> бонусного опыта за игру в рулетку.", parse_mode="HTML")
        else:
            # Мутим пользователя
            until_date = datetime.now() + timedelta(minutes=mute_minutes)
            try:
                if await is_admin(bot, message.chat.id, message.from_user.id):
                    await message.reply("Администратор выйди разбийник...")
                else:
                    await bot.restrict_chat_member(
                        chat_id=message.chat.id,
                        user_id=message.from_user.id,
                        permissions=ChatPermissions(can_send_messages=False),
                        until_date=until_date
                    )
                    await message.reply("Для быстрого снятия мута, вложитесь в хостинг")
            except Exception as e:
                await message.reply("Ошибка при попытке замутить пользователя. Проверьте права бота или не играйте будучи админом.")
                logger.error(f"Ошибка в roulette mute: {e}")
    except Exception as e:
        logger.error(f"Ошибка в roulette: {e}")
        await message.reply("Ошибка в игре рулетка.")

@router.message(Command("help"))
async def help_command(message: Message) -> None:
    # Отсеиваем привязанный канал и сообщения бота
    if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
        return
    text = (
        "<b>🤖 Добро пожаловать! Вот что я умею:</b>\n\n"
        "<b>👤 Пользовательские команды:</b>\n"
        "<b>/stat</b> — Ваша статистика в чате: сколько сообщений, сколько вы с нами\n"
        "<b>/burmalda</b> — 🎮 <i>Игровая система с кредитами и магазином!</i>\n"
        "<b>/size</b> — Узнай размер своего бубуя (рандом + никнейм)\n"
        "<b>/size_top</b> — Турнирная таблица размеров за сегодня\n"
        "<b>/anekdot</b> — Получить свежий анекдот (лимит: 3 в день)\n"
        "<b>/roulette &lt;минуты&gt;</b> — <i>Русская рулетка!</i>\n"
        "    Пример: <code>/roulette 5</code> — если не повезёт, получите мут на 5 минут\n"
        "<b>/rules</b> — Показать правила чата\n"
        "<b>/links</b> — Список полезных ссылок с кнопками\n"
        "<b>/help</b> — Это меню\n"
        "\n"
        "<b>🛠️ Админ-команды:</b>\n"
        "<b>/set_welcome</b> — Изменить приветствие (ответом на сообщение или текстом)\n"
        "<b>/set_bye</b> — Изменить прощание (ответом на сообщение или текстом)\n"
        "<b>/add_button</b> — Добавить кнопку в /links. Пример: <code>/add_button Название - https://ссылка;</code>\n"
        "<b>/del_button</b> — Удалить кнопку из /links. Пример: <code>/del_button Название;</code>\n"
        "<b>/add_rules</b> — Добавить или обновить правила чата (ответом на сообщение с текстом)\n"
        "<b>/m</b> — Мут пользователя (ответом на сообщение, можно указать срок: <code>/m 10m</code>)\n"
        "<b>/b</b> — Бан пользователя (ответом на сообщение, можно указать срок: <code>/b 1d</code>)\n"
        "\n"
        "<b>🎮 Burmalda - Игровая система:</b>\n"
        "• Ежедневно получайте 100 отвальчиков\n"
        "• Играйте в рулетку, слоты и блэкджек за 30 отвальчиков\n"
        "• Каждая игра включает 3 попытки (кроме блэкджека - 1 попытка)\n"
        "• Зарабатывайте отвальчики и бонусный опыт за победы:\n"
        "  - 1 победа: 15 отвальчиков + 30 бонусного опыта\n"
        "  - 2 победы: 35 отвальчиков + 60 бонусного опыта\n"
        "  - 3 победы: 60 отвальчиков + 90 бонусного опыта\n"
        "• Покупайте товары в магазине: снятие предупреждений, обмен отвальчиков на опыт\n"
        "\n"
        "<b>ℹ️ Примечания:</b>\n"
        "• <b>Мут</b> — временно запрещает писать сообщения.\n"
        "• <b>Бан</b> — удаляет пользователя из чата.\n"
        "• Для работы админ-команд бот должен быть админом с нужными правами!\n"
        "• Для /roulette бот должен иметь право ограничивать пользователей.\n"
        "\n"
        "<i>Если что-то не работает — проверьте права бота или обратитесь к разработчику.</i>"
    )
    await message.reply(text, parse_mode="HTML")

@router.message(Command("killchatall"))
async def killchatall(message: Message, bot: Bot) -> None:
    """
    Секретная команда для полного уничтожения чата:
    - Удаляет все сообщения (по максимуму, с таймаутом)
    - Удаляет закреплённые сообщения, фото, описание, название чата
    - Сбрасывает меню команд
    - Исключает всех пользователей, которых может
    - Очищает все таблицы в базе
    - Бот выходит из чата
    Пароль берётся из config.py (KILL_CHAT_PASSWORD)
    """
    try:
        # Отсеиваем привязанный канал и сообщения бота
        if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
            await message.reply("Команды нельзя использовать от имени канала.")
            return
        args = message.text.split()
        if len(args) < 2 or args[1] != KILL_CHAT_PASSWORD:
            await message.reply("❌ Неверный пароль.")
            return
        chat_id = message.chat.id
        await message.reply("⚠️ Запущено полное уничтожение чата! Попытка удалить всё...")
        # 0. Попытка удалить закреплённые сообщения
        try:
            await bot.unpin_all_chat_messages(chat_id)
        except Exception:
            pass
        # 1. Попытка удалить фото, описание, название чата
        try:
            await bot.delete_chat_photo(chat_id)
        except Exception:
            pass
        try:
            await bot.set_chat_title(chat_id, "Удалено")
        except Exception:
            pass
        try:
            await bot.set_chat_description(chat_id, "")
        except Exception:
            pass
        # 2. Сброс меню команд
        try:
            await bot.set_my_commands([], scope={"type": "chat", "chat_id": chat_id})
        except Exception:
            pass
        # 3. Удалить как можно больше сообщений (цикл по истории, с таймаутом)
        try:
            last_message_id = None
            for _ in range():  # 20*1000 = 20 000 сообщений максимум
                messages = []
                async for msg in bot.get_chat_history(chat_id, limit=1000, offset_id=last_message_id or 0):
                    messages.append(msg)
                if not messages:
                    break
                for msg in messages:
                    try:
                        await bot.delete_message(chat_id, msg.message_id)
                        await asyncio.sleep(0.05)  # 20 сообщений в секунду (лимит Telegram)
                    except Exception:
                        pass
                last_message_id = messages[-1].message_id if messages else None
                await asyncio.sleep(1)  # Пауза между пачками
                if not last_message_id:
                    break
        except Exception:
            pass
        # 4. Исключить всех пользователей (кроме админов и ботов)
        try:
            admins = await bot.get_chat_administrators(chat_id)
            admin_ids = {admin.user.id for admin in admins}
            members = []
            async for member in bot.get_chat_members(chat_id):
                members.append(member)
            for member in members:
                uid = member.user.id
                if uid not in admin_ids and not member.user.is_bot:
                    try:
                        await bot.ban_chat_member(chat_id, uid)
                        await bot.unban_chat_member(chat_id, uid)
                        await asyncio.sleep(0.1)
                    except Exception:
                        pass
        except Exception:
            pass
        # 5. Очистить все таблицы в базе
        try:
            from model import db
            db.execute_sql("TRUNCATE TABLE user_list, anek_list, chat_list, button_list, size_list, ban_list, text RESTART IDENTITY CASCADE;")
        except Exception:
            pass
        # 6. Бот выходит из чата
        try:
            await bot.leave_chat(chat_id)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Ошибка в killchatall: {e}")
        try:
            await message.reply("Ошибка при выполнении команды killchatall.")
        except Exception:
            pass

@router.message(Command("warn"))
async def warn_user(message: Message, bot: Bot) -> None:
    """Выдать предупреждение пользователю."""
    # Отсеиваем привязанный канал и сообщения бота
    if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
        return
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Только администратор может использовать эту команду.")
        return

    try:
        if not message.reply_to_message:
            await message.reply("Ответьте на сообщение пользователя, чтобы выдать предупреждение.")
            return

        user_id = message.reply_to_message.from_user.id
        chat_id = message.chat.id
        warned_name = message.reply_to_message.from_user.username if message.reply_to_message.from_user.username is not None else message.reply_to_message.from_user.first_name
        admin_name = message.from_user.username if message.from_user.username is not None else message.from_user.first_name

        # Обновляем/создаём warn_count
        q = (
            User_listModel
            .insert({
                User_listModel.created_at: fn.now(),
                User_listModel.user_id: user_id,
                User_listModel.last_visit: fn.now(),
                User_listModel.warn_count: 1,
                User_listModel.rank: 1,  # Начальный уровень
            })
            .on_conflict(
                conflict_target=[User_listModel.user_id],
                update={User_listModel.warn_count: User_listModel.warn_count + 1, User_listModel.last_visit: fn.now()}
            )
        )
        q.execute()
        # Получаем новое значение warn_count
        user_record = User_listModel.get(User_listModel.user_id == user_id)

        # Проверяем количество предупреждений
        if user_record.warn_count >= 3:
            # Баним пользователя
            try:
                await bot.ban_chat_member(chat_id, user_id)
                await bot.unban_chat_member(chat_id, user_id)  # кик
                await message.reply(
                    f"Пользователь <b>{warned_name}</b> получил 3 предупреждения и был удален из чата.",
                    parse_mode="HTML"
                )
                # Сбрасываем счетчик предупреждений
                User_listModel.update({User_listModel.warn_count: 0}).where(User_listModel.user_id == user_id).execute()
            except Exception as e:
                logger.error(f"Ошибка при бане пользователя: {e}")
                await message.reply("Не удалось удалить пользователя. Проверьте права бота.")
        else:
            await message.reply(
                f"Пользователю <b>{warned_name}</b> выдано предупреждение ({user_record.warn_count}/3). "
                f"3 предупреждения — Бан!",
                parse_mode="HTML"
            )

    except Exception as e:
        logger.error(f"Ошибка в warn_user: {e}")
        await message.reply("Произошла ошибка при выдаче предупреждения.")

@router.message(Command("unwarn"))
async def unwarn_user(message: Message, bot: Bot) -> None:
    """Снять все предупреждения у пользователя."""
    # Отсеиваем привязанный канал и сообщения бота
    if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
        return
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Только администратор может использовать эту команду.")
        return

    try:
        if not message.reply_to_message:
            await message.reply("Ответьте на сообщение пользователя, чтобы снять предупреждения.")
            return

        user_id = message.reply_to_message.from_user.id
        user_name = message.reply_to_message.from_user.username if message.reply_to_message.from_user.username is not None else message.reply_to_message.from_user.first_name
        admin_name = message.from_user.username if message.from_user.username is not None else message.from_user.first_name

        # Сбрасываем счетчик предупреждений
        q = User_listModel.update({User_listModel.warn_count: 0}).where(User_listModel.user_id == user_id)
        updated = q.execute()
        user_record = User_listModel.get_or_none(User_listModel.user_id == user_id)
        old_warn_count = user_record.warn_count if user_record else 0

        if not user_record or old_warn_count == 0:
            await message.reply(f"У пользователя <b>{user_name}</b> нет предупреждений.", parse_mode="HTML")
            return

        await message.reply(
            f"Администратор <b>{admin_name}</b> снял все предупреждения ({old_warn_count}) у пользователя <b>{user_name}</b>.",
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка в unwarn_user: {e}")
        await message.reply("Произошла ошибка при снятии предупреждений.")

# --- Админ-команды ---

@router.message(Command("m"))
async def admin_mute(message: Message, bot: Bot) -> None:
    # Отсеиваем привязанный канал и сообщения бота
    if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
        return
    # Эта команда не трогает поле is_verified, только мутит пользователя
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Только администратор может использовать эту команду.")
        return
    try:
        if not message.reply_to_message:
            await message.reply("Ответьте на сообщение пользователя, чтобы замутить его.")
            return
        user_id = message.reply_to_message.from_user.id
        muted_name = message.reply_to_message.from_user.username if message.reply_to_message.from_user.username is not None else message.reply_to_message.from_user.first_name
        admin_name = message.from_user.username if message.from_user.username is not None else message.from_user.first_name
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
            f"Пользователь <b>{muted_name}</b> был замучен админом <b>{admin_name}</b> {time_str}.\n"
            f"Размут: <b>{unmute_time}</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка в admin_mute: {e}")
        await message.reply("Ошибка при муте пользователя.")

@router.message(Command("b"))
async def admin_ban(message: Message, bot: Bot) -> None:
    # Отсеиваем привязанный канал и сообщения бота
    if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
        return

    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Только администратор может использовать эту команду.")
        return
    try:
        if not message.reply_to_message:
            await message.reply("Ответьте на сообщение пользователя, чтобы забанить его.")
            return
        user_id = message.reply_to_message.from_user.id
        admin_name = message.from_user.username if message.from_user.username is not None else message.from_user.first_name
        banned_name = message.reply_to_message.from_user.username if message.reply_to_message.from_user.username is not None else message.reply_to_message.from_user.first_name
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
            f"Пользователь <b>{banned_name}</b> был забанен админом <b>{admin_name}</b> {time_str}.\n"
            f"Разбан: <b>{unban_time}</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка в admin_ban: {e}")
        await message.reply("Ошибка при бане пользователя.")



# --- Burmalda система ---

@router.message(Command("burmalda"))
async def burmalda_command(message: Message, bot: Bot) -> None:
    """Главная команда для доступа к игровой системе Burmalda"""
    try:
        # Отсеиваем привязанный канал и сообщения бота
        if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
            await message.reply("Команды нельзя использовать от имени канала.")
            return
            
        user_id = message.from_user.id
        username = message.from_user.username if message.from_user.username is not None else message.from_user.first_name
        
        # Проверяем и выдаем ежедневные кредиты
        daily_credits = await burmalda_game.check_and_give_daily_credits(user_id)
        
        # Создаем главное меню
        text, markup = burmalda_game.create_main_menu(user_id)
        
        # Добавляем информацию о ежедневных кредитах
        if daily_credits > 0:
            text += f"\n\n🎁 <b>Получено {daily_credits} ежедневных кредитов!</b>"
        
        await message.reply(text, reply_markup=markup, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка в команде burmalda для user_id {message.from_user.id}: {e}")
        await message.reply("❌ Произошла ошибка при открытии игровой системы.")

@router.callback_query(F.data.startswith("burmalda_finish_"))
async def burmalda_finish_callback(call: CallbackQuery, bot: Bot) -> None:
    await finish_burmalda_game(call, bot)

@router.callback_query(F.data.startswith("burmalda_"))
async def burmalda_callback(call: CallbackQuery, bot: Bot) -> None:
    # Если это завершение игры, не обрабатываем здесь, а даём сработать finish_burmalda_game
    if call.data.startswith("burmalda_finish_"):
        return
    try:
        data = call.data.split("_")
        if len(data) < 3:
            await call.answer("❌ Неверный формат данных")
            return
            
        action = data[1]
        
        if action == "main":
            # Главное меню
            user_id = int(data[2])
            
            # Проверяем, что callback отправил тот же пользователь
            if call.from_user.id != user_id:
                await call.answer("❌ Это не ваше меню!", show_alert=True)
                return
                
            text, markup = burmalda_game.create_main_menu(user_id)
            await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
            
        elif action == "shop":
            # Магазин
            user_id = int(data[2])
            
            # Проверяем, что callback отправил тот же пользователь
            if call.from_user.id != user_id:
                await call.answer("❌ Это не ваше меню!", show_alert=True)
                return
                
            text, markup = burmalda_game.create_shop_menu(user_id)
            await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
            
        elif action == "game":
            # Игра
            if len(data) < 4:
                await call.answer("❌ Неверный формат данных игры")
                return
                
            game_type = data[2]
            user_id = int(data[3])
            
            # Проверяем, что callback отправил тот же пользователь
            if call.from_user.id != user_id:
                await call.answer("❌ Это не ваша игра!", show_alert=True)
                return
            
            # Проверяем, есть ли уже активная игра
            game_state = burmalda_game.active_games.get(user_id)
            
            if game_state:
                # Если тип игры отличается, не даём начать новую
                if game_state.get("game_type") != game_type:
                    await call.answer("Сначала завершите текущую игру!", show_alert=True)
                    return
            else:
                # Начинаем новую игру - проверяем кредиты
                credits = burmalda_game.get_user_credits(user_id)
                if credits < GAME_COST:
                    await call.answer(f"❌ Недостаточно отвальчиков! Нужно: {GAME_COST}, у вас: {credits}", show_alert=True)
                    return
                    
                # Тратим кредиты за всю игру
                if not burmalda_game.spend_credits(user_id, GAME_COST):
                    await call.answer("❌ Ошибка при списании отвальчиков", show_alert=True)
                    return
                    
                # Инициализируем новую игру
                burmalda_game.active_games[user_id] = {
                    "game_type": game_type,
                    "attempts": 0,
                    "wins": 0,
                    "messages": []
                }
            # Удаляем меню выбора игры
            try:
                await call.message.delete()
            except Exception:
                pass
            # Начинаем/продолжаем игру
            await start_burmalda_game(call, bot, user_id, game_type)
            
        elif action == "remove":
            # Снятие предупреждения
            if len(data) < 4 or data[2] != "warn":
                await call.answer("❌ Неверный формат данных", show_alert=True)
                return
            user_id = int(data[3])
            
            # Проверяем, что callback отправил тот же пользователь
            if call.from_user.id != user_id:
                await call.answer("❌ Это не ваше меню!", show_alert=True)
                return
                
            q = (
                User_listModel
                .select(User_listModel.warn_count)
                .where(User_listModel.user_id == user_id)
                .first()
            )
            
            if not q or q.warn_count == 0:
                await call.answer("❌ У вас нет предупреждений для снятия", show_alert=True)
                return
                
            points = burmalda_game.get_user_points(user_id)
            if points < WARN_REMOVAL_COST:
                await call.answer(f"❌ Недостаточно отвальчиков! Нужно: {WARN_REMOVAL_COST}, у вас: {points}", show_alert=True)
                return
                
            # Снимаем предупреждение и тратим отвальчики
            (
                User_listModel
                .update({
                    User_listModel.warn_count: User_listModel.warn_count - 1
                })
                .where(User_listModel.user_id == user_id)
            ).execute()
            
            burmalda_game.spend_points(user_id, WARN_REMOVAL_COST)
            
            await call.answer(f"✅ Предупреждение снято! Потрачено {WARN_REMOVAL_COST} отвальчиков", show_alert=True)
            
            # Обновляем меню магазина
            text, markup = burmalda_game.create_shop_menu(user_id)
            await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
            
        elif action == "exchange":
            # Обмен очков на опыт
            if len(data) < 4 or data[-2] != "exp":
                await call.answer("❌ Неверный формат данных", show_alert=True)
                return
            user_id = int(data[-1])
            # Проверяем, что callback отправил тот же пользователь
            if call.from_user.id != user_id:
                await call.answer("❌ Это не ваше меню!", show_alert=True)
                return
            q = (
                User_listModel
                .select(User_listModel.rank)
                .where(User_listModel.user_id == user_id)
                .first()
            )
            if not q:
                await call.answer("❌ Пользователь не найден", show_alert=True)
                return
            points = burmalda_game.get_user_points(user_id)
            if points < 100:
                await call.answer(f"❌ Недостаточно отвальчиков! Нужно: 100, у вас: {points}", show_alert=True)
                return
            # Рассчитываем опыт за каждые 100 отвальчиков
            commission = burmalda_game.get_commission_rate(q.rank)
            exp_gained = int(100 * (1 - commission))
            # Тратим отвальчики и начисляем опыт
            burmalda_game.spend_points(user_id, 100)
            await award_exp_and_check_level_up(user_id, exp_gained, 0, call.from_user.first_name, call.message, bot)
            await call.answer(f"✅ Получено {exp_gained} опыта за 100 отвальчиков! Комиссия: {commission*100:.0f}%", show_alert=True)
            # Обновляем меню магазина
            text, markup = burmalda_game.create_shop_menu(user_id)
            await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
            
        else:
            await call.answer("❌ Неизвестное действие")
            
    except Exception as e:
        logger.error(f"Ошибка в burmalda_callback: {e}")
        await call.answer("❌ Произошла ошибка", show_alert=True)

async def start_burmalda_game(call: CallbackQuery, bot: Bot, user_id: int, game_type: str) -> None:
    """Начинает игру в Burmalda"""
    try:
        game_state = burmalda_game.active_games.get(user_id)
        if not game_state:
            await call.answer("❌ Игра не найдена", show_alert=True)
            return
            
        # Проверяем количество попыток
        if game_state["attempts"] >= GAME_ATTEMPTS:
            await call.answer("❌ Все попытки использованы! Завершите игру.", show_alert=True)
            return
            
        game_state["attempts"] += 1
        
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        
        if game_type == "slot":
            result = await burmalda_game.play_slot_game(user_id)
            if result.won:
                game_state["wins"] += 1
                
            # Добавляем информацию о попытках
            attempts_info = f"\n\n🎯 Попытка {game_state['attempts']}/{GAME_ATTEMPTS}"
            if game_state["attempts"] < GAME_ATTEMPTS:
                attempts_info += f"\n🏆 Победы: {game_state['wins']}"
                # Добавляем кнопку для следующей попытки
                builder.button(text="🎰 Следующая попытка", callback_data=f"burmalda_game_slot_{user_id}")
                builder.button(text="🏁 Завершить игру", callback_data=f"burmalda_finish_{user_id}")
                builder.adjust(2)
            else:
                attempts_info += f"\n🏆 Итого побед: {game_state['wins']}"
                # Добавляем только кнопку завершения
                builder.button(text="🏁 Завершить игру", callback_data=f"burmalda_finish_{user_id}")
                builder.adjust(1)
            
            # Отправляем результат с информацией о попытках
            new_message = await bot.send_message(
                chat_id=call.message.chat.id,
                text=result.message + attempts_info,
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
            game_state["messages"].append(new_message.message_id)
            
        elif game_type == "roulette":
            result = await burmalda_game.play_roulette_game(user_id)
            if result.won:
                game_state["wins"] += 1
                
            # Добавляем информацию о попытках
            attempts_info = f"\n\n🎯 Попытка {game_state['attempts']}/{GAME_ATTEMPTS}"
            if game_state["attempts"] < GAME_ATTEMPTS:
                attempts_info += f"\n🏆 Победы: {game_state['wins']}"
                # Добавляем кнопку для следующей попытки
                builder.button(text="🎲 Следующая попытка", callback_data=f"burmalda_game_roulette_{user_id}")
                builder.button(text="🏁 Завершить игру", callback_data=f"burmalda_finish_{user_id}")
                builder.adjust(2)
            else:
                attempts_info += f"\n🏆 Итого побед: {game_state['wins']}"
                # Добавляем только кнопку завершения
                builder.button(text="🏁 Завершить игру", callback_data=f"burmalda_finish_{user_id}")
                builder.adjust(1)
            
            # Отправляем результат с информацией о попытках
            new_message = await bot.send_message(
                chat_id=call.message.chat.id,
                text=result.message + attempts_info,
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
            game_state["messages"].append(new_message.message_id)
            
        elif game_type == "blackjack":
            # --- Новый поэтапный блэкджек ---
            # Если первый запуск — раздаём карты
            if "player_cards" not in game_state:
                import random
                cards = list(range(2, 11)) + [10, 10, 10]  # 2-10, J, Q, K = 10
                # Классика: только две карты игроку и две дилеру
                player_cards = [random.choice(cards), random.choice(cards)]
                dealer_cards = [random.choice(cards), random.choice(cards)]
                game_state["player_cards"] = player_cards
                game_state["dealer_cards"] = dealer_cards
                game_state["game_over"] = False
            player_cards = game_state["player_cards"]
            dealer_cards = game_state["dealer_cards"]
            # Считаем очки игрока
            player_score = sum(player_cards)
            while player_score > 21 and 11 in player_cards:
                player_cards[player_cards.index(11)] = 1
                player_score = sum(player_cards)
            # Показываем только одну карту дилера
            dealer_visible = dealer_cards[0]
            # Кнопки
            builder.button(text="Взять карту", callback_data=f"blackjack_hit_{user_id}")
            builder.button(text="Стоп", callback_data=f"blackjack_stand_{user_id}")
            builder.adjust(2)
            # Сообщение
            player_cards_str = ", ".join(map(str, player_cards))
            text = (
                f"🃏 <b>Блэкджек</b>\n\n"
                f"Ваши карты: {player_cards_str}\n"
                f"Ваши очки: <b>{player_score}</b>\n\n"
                f"Карта дилера: {dealer_visible}, ?\n"
            )
            new_message = await bot.send_message(
                chat_id=call.message.chat.id,
                text=text,
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
            game_state["messages"].append(new_message.message_id)
            
        else:
            await call.answer("❌ Неизвестная игра", show_alert=True)
            return
            
        await call.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в start_burmalda_game: {e}")
        await call.answer("❌ Ошибка в игре", show_alert=True)

async def finish_burmalda_game(call: CallbackQuery, bot: Bot) -> None:
    """Завершает игру в Burmalda и начисляет награды"""
    try:
        logger.info(f"[finish_burmalda_game] Начало. user_id={call.from_user.id}, data={call.data}, chat_id={call.message.chat.id}")
        await call.answer()  # Сразу убираем "часики" у пользователя
        user_id = int(call.data.split("_")[2])
        logger.info(f"[finish_burmalda_game] user_id из callback: {user_id}")
        # Проверяем, что callback отправил тот же пользователь
        if call.from_user.id != user_id:
            logger.warning(f"[finish_burmalda_game] Попытка завершения не своим пользователем: {call.from_user.id} != {user_id}")
            await call.answer("❌ Это не ваша игра!", show_alert=True)
            return
        game_state = burmalda_game.active_games.get(user_id)
        logger.info(f"[finish_burmalda_game] game_state: {game_state}")
        if not game_state:
            logger.warning(f"[finish_burmalda_game] Игра не найдена для user_id={user_id}")
            await call.answer("❌ Игра не найдена", show_alert=True)
            return
            
        # Проверяем, что игра действительно завершена (для блэкджека)
        if game_state.get("game_type") == "blackjack" and not game_state.get("game_over"):
            await call.answer("❌ Сначала завершите игру в блэкджек!", show_alert=True)
            return
            
        wins = game_state["wins"]
        points_earned = ATTEMPT_REWARDS.get(wins, 0)
        bonus_exp_earned = VICTORY_BONUS_EXP.get(wins, 0)
        logger.info(f"[finish_burmalda_game] wins={wins}, points_earned={points_earned}, bonus_exp_earned={bonus_exp_earned}")
        # Начисляем отвальчики
        if points_earned > 0:
            logger.info(f"[finish_burmalda_game] Добавляю отвальчики: {points_earned}")
            burmalda_game.add_points(user_id, points_earned)
        # Начисляем бонусный опыт за победы
        if bonus_exp_earned > 0:
            logger.info(f"[finish_burmalda_game] Добавляю бонусный опыт: {bonus_exp_earned}")
            burmalda_game.add_bonus_exp(user_id, bonus_exp_earned)
        # Формируем итоговое сообщение
        if wins == 0:
            result_text = "😔 К сожалению, вы не выиграли ни одной попытки..."
        elif wins == 1:
            result_text = f"🎉 Хорошо! Вы выиграли 1 попытку и получаете {points_earned} отвальчиков и {bonus_exp_earned} бонусного опыта!"
        elif wins == 2:
            result_text = f"🎊 Отлично! Вы выиграли 2 попытки и получаете {points_earned} отвальчиков и {bonus_exp_earned} бонусного опыта!"
        else:
            result_text = f"🏆 Превосходно! Вы выиграли все 3 попытки и получаете {points_earned} отвальчиков и {bonus_exp_earned} бонусного опыта!"
        logger.info(f"[finish_burmalda_game] Удаляю сообщения игры: {game_state['messages']}")
        # Удаляем все сообщения игры
        for msg_id in game_state["messages"]:
            try:
                await bot.delete_message(call.message.chat.id, msg_id)
                logger.info(f"[finish_burmalda_game] Удалено сообщение {msg_id}")
            except Exception as e:
                logger.error(f"[finish_burmalda_game] Не удалось удалить сообщение {msg_id}: {e}")
        # Удаляем текущее сообщение
        try:
            await call.message.delete()
            logger.info(f"[finish_burmalda_game] Удалено текущее сообщение")
        except Exception as e:
            logger.error(f"[finish_burmalda_game] Не удалось удалить текущее сообщение: {e}")
        # Отправляем новое главное меню Burmalda
        try:
            logger.info(f"[finish_burmalda_game] Формирую главное меню для user_id={user_id}")
            text, markup = burmalda_game.create_main_menu(user_id)
            logger.info(f"[finish_burmalda_game] Главное меню сформировано. text={text[:50]}...")
            await bot.send_message(
                chat_id=call.message.chat.id,
                text=text,
                reply_markup=markup,
                parse_mode="HTML"
            )
            logger.info(f"[finish_burmalda_game] Главное меню отправлено")
        except Exception as e:
            logger.error(f"[finish_burmalda_game] Ошибка при отправке главного меню: {e}")
            await bot.send_message(call.message.chat.id, "Ошибка при формировании меню.")
        # Очищаем состояние игры (явно)
        if user_id in burmalda_game.active_games:
            del burmalda_game.active_games[user_id]
            logger.info(f"[finish_burmalda_game] Состояние игры очищено для user_id={user_id}")
        # Fallback: если где-то ещё есть состояния, сбросить их (расширяем при необходимости)
    except Exception as e:
        logger.error(f"[finish_burmalda_game] Глобальная ошибка: {e}")
        await call.answer("❌ Ошибка при завершении игры", show_alert=True)


# --- Обработчики событий ---

@router.message()
async def handle_all_messages(message: Message, bot: Bot) -> None:
    """
    Обработчик всех сообщений для обновления статистики пользователей.
    Обновляет last_visit, message_count и начисляет опыт.
    """
    try:
        # Пропускаем сообщения от ботов и каналов
        if message.from_user and message.from_user.is_bot:
            return
        if message.chat.type == "channel":
            return

        user_id = message.from_user.id

        # Обновляем/создаем запись пользователя
        (
            User_listModel
            .insert({
                User_listModel.created_at: fn.now(),
                User_listModel.user_id: user_id,
                User_listModel.message_count: 1,
                User_listModel.last_visit: fn.now(),
                User_listModel.rank: 1,  # Начальный уровень
                User_listModel.credits: 0,  # Начальные отвальчики
            })
            .on_conflict(
                conflict_target=[User_listModel.user_id],
                update={
                    User_listModel.message_count: User_listModel.message_count + 1,
                    User_listModel.last_visit: fn.now()
                }
            )
        ).execute()

        # Фильтруем команды
        if message.text and message.text.startswith("/"):
            try:
                await message.delete()
            except Exception as e:
                logger.error(f"Не удалось удалить команду в чате {message.chat.id}: {e}")
            return

        username = message.from_user.username if message.from_user.username is not None else message.from_user.first_name
        total_exp_to_award = 0
        level_exp_to_award = 0
        bonus_exp_to_award = 0

        # Проверяем винстрик
        is_new_day, streak = check_visit_streak(user_id)
        if is_new_day and streak > 1:
            # Начисляем опыт за винстрик
            streak_exp = 10 * streak
            level_exp_to_award += streak_exp
            total_exp_to_award += streak_exp

            await message.reply(
                f"🎉 <b>{username}</b>, в чате {streak}-й день подряд!\nВы получаете <b>{streak_exp}</b> опыта за активность!",
                parse_mode="HTML"
            )

        # Проверяем шанс получения бонусного опыта (1%)
        if random.random() < 0.01:
            bonus_exp = random.randint(10, 100)
            bonus_exp_to_award += bonus_exp
            total_exp_to_award += bonus_exp

            await message.reply(
                f"🎲 <b>{username}</b> получает <b>{bonus_exp}</b> бонусного опыта за активность!",
                parse_mode="HTML"
            )

        # Начисляем опыт за сообщение
        level_exp_to_award += 1
        total_exp_to_award += 1

        # Начисляем весь накопленный опыт и проверяем повышение уровня
        if total_exp_to_award > 0:
            await award_exp_and_check_level_up(user_id, level_exp_to_award, bonus_exp_to_award, username, message, bot)

    except Exception as e:
        logger.error(f"Ошибка в handle_all_messages для user_id {message.from_user.id}: {e}")

@router.callback_query(F.data.startswith("blackjack_hit_"))
async def blackjack_hit_callback(call: CallbackQuery, bot: Bot) -> None:
    await process_blackjack_hit(call, bot)

@router.callback_query(F.data.startswith("blackjack_stand_"))
async def blackjack_stand_callback(call: CallbackQuery, bot: Bot) -> None:
    await process_blackjack_stand(call, bot)

async def process_blackjack_hit(call: CallbackQuery, bot: Bot) -> None:
    user_id = int(call.data.split('_')[-1])
    game_state = burmalda_game.active_games.get(user_id)
    if not game_state or game_state.get("game_over"):
        await call.answer("Игра уже завершена или не найдена", show_alert=True)
        return
    # Добавляем карту игроку
    cards = list(range(2, 11)) + [10, 10, 10]  # 2-10, J, Q, K = 10
    aces = [11]
    card = random.choice(cards + aces)
    game_state["player_cards"].append(card)
    # Считаем очки
    player_cards = game_state["player_cards"]
    player_score = sum(player_cards)
    while player_score > 21 and 11 in player_cards:
        player_cards[player_cards.index(11)] = 1
        player_score = sum(player_cards)
    dealer_visible = game_state["dealer_cards"][0]
    # Проверка на перебор
    if player_score > 21:
        game_state["game_over"] = True
        # Показываем финал
        await show_blackjack_final(call, bot, user_id, player_bust=True)
        return
    # Иначе продолжаем игру
    builder = InlineKeyboardBuilder()
    builder.button(text="Взять карту", callback_data=f"blackjack_hit_{user_id}")
    builder.button(text="Стоп", callback_data=f"blackjack_stand_{user_id}")
    builder.adjust(2)
    player_cards_str = ", ".join(map(str, player_cards))
    text = (
        f"🃏 <b>Блэкджек</b>\n\n"
        f"Ваши карты: {player_cards_str}\n"
        f"Ваши очки: <b>{player_score}</b>\n\n"
        f"Карта дилера: {dealer_visible}, ?\n"
    )
    # Редактируем последнее сообщение
    try:
        last_msg_id = game_state["messages"][-1]
        await bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=last_msg_id,
            text=text,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    except Exception:
        # Если не удалось — отправляем новое
        new_message = await bot.send_message(
            chat_id=call.message.chat.id,
            text=text,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        game_state["messages"].append(new_message.message_id)
    await call.answer()

async def process_blackjack_stand(call: CallbackQuery, bot: Bot) -> None:
    user_id = int(call.data.split('_')[-1])
    game_state = burmalda_game.active_games.get(user_id)
    if not game_state or game_state.get("game_over"):
        await call.answer("Игра уже завершена или не найдена", show_alert=True)
        return
    # Дилер доигрывает
    dealer_cards = game_state["dealer_cards"]
    player_cards = game_state["player_cards"]
    player_score = sum(player_cards)
    while player_score > 21 and 11 in player_cards:
        player_cards[player_cards.index(11)] = 1
        player_score = sum(player_cards)
    dealer_score = sum(dealer_cards)
    while dealer_score < 17:
        card = random.choice(list(range(2, 11)) + [10, 10, 10] + [11])
        dealer_cards.append(card)
        dealer_score = sum(dealer_cards)
        while dealer_score > 21 and 11 in dealer_cards:
            dealer_cards[dealer_cards.index(11)] = 1
            dealer_score = sum(dealer_cards)
    game_state["game_over"] = True
    await show_blackjack_final(call, bot, user_id, player_bust=False)
    await call.answer()

async def show_blackjack_final(call: CallbackQuery, bot: Bot, user_id: int, player_bust: bool):
    game_state = burmalda_game.active_games.get(user_id)
    player_cards = game_state["player_cards"]
    dealer_cards = game_state["dealer_cards"]
    player_score = sum(player_cards)
    while player_score > 21 and 11 in player_cards:
        player_cards[player_cards.index(11)] = 1
        player_score = sum(player_cards)
    dealer_score = sum(dealer_cards)
    while dealer_score > 21 and 11 in dealer_cards:
        dealer_cards[dealer_cards.index(11)] = 1
        dealer_score = sum(dealer_cards)
    player_cards_str = ", ".join(map(str, player_cards))
    dealer_cards_str = ", ".join(map(str, dealer_cards))
    # Определяем результат
    if player_bust:
        result = "❌ Перебор! Вы проиграли."
        won = False
    elif dealer_score > 21 or player_score > dealer_score:
        result = "🎉 Победа!"
        won = True
    elif player_score == dealer_score:
        result = "🤝 Ничья!"
        won = False
    else:
        result = "❌ Проигрыш."
        won = False
    text = (
        f"🃏 <b>Блэкджек</b>\n\n"
        f"Ваши карты: {player_cards_str}\n"
        f"Ваши очки: <b>{player_score}</b>\n\n"
        f"Карты дилера: {dealer_cards_str}\n"
        f"Очки дилера: <b>{dealer_score}</b>\n\n"
        f"{result}"
    )
    # Удаляем старое сообщение
    try:
        last_msg_id = game_state["messages"][-1]
        await bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=last_msg_id,
            text=text,
            reply_markup=None,
            parse_mode="HTML"
        )
    except Exception:
        new_message = await bot.send_message(
            chat_id=call.message.chat.id,
            text=text,
            parse_mode="HTML"
        )
        game_state["messages"].append(new_message.message_id)
    # Если победа — увеличиваем счётчик побед
    if won:
        game_state["wins"] += 1
    # Показываем кнопку завершения игры
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="🏁 Завершить игру", callback_data=f"burmalda_finish_{user_id}")
    builder.adjust(1)
    await bot.send_message(
        chat_id=call.message.chat.id,
        text="Вы можете завершить игру или начать новую.",
        reply_markup=builder.as_markup()
    )