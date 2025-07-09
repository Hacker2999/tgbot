import logging
from datetime import datetime, timedelta, timezone
import random
import re
import asyncio
import hashlib
from typing import Optional, Dict, List, Tuple
from functools import lru_cache
import json

from aiogram import Router, Bot, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated, BotCommand, MenuButtonCommands, ChatPermissions, CallbackQuery
from aiogram.filters import Command, ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from aiogram.utils.keyboard import InlineKeyboardBuilder
from peewee import fn, DatabaseError

from baneks_api import fetch_random_joke
from model import TextModel, AnekModel, User_listModel, Chat_listModel, Button_listModel, SizeModel, RpActionModel
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
                    User_listModel.chat_id: chat_id,
                    User_listModel.user_id: user_id,
                    User_listModel.is_verified: True,
                    User_listModel.last_visit: fn.now(),
                })
                .on_conflict(
                    conflict_target=[User_listModel.chat_id, User_listModel.user_id],
                    update={User_listModel.is_verified: True, User_listModel.last_visit: fn.now()}
                )
            ).execute()
            return  # Не показываем капчу
        # 1. Обновить/создать запись пользователя с is_verified=False
        (
            User_listModel
            .insert({
                User_listModel.created_at: fn.now(),
                User_listModel.chat_id: chat_id,
                User_listModel.user_id: user_id,
                User_listModel.is_verified: False,
                User_listModel.last_visit: fn.now(),
                User_listModel.rank: 1,  # Начальный уровень
            })
            .on_conflict(
                conflict_target=[User_listModel.chat_id, User_listModel.user_id],
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
            user = User_listModel.select(User_listModel.is_verified).where(
                User_listModel.chat_id == chat_id,
                User_listModel.user_id == user_id
            ).first()
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
                        User_listModel.chat_id == chat_id,
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
                        .where(TextModel.chat_id == chat_id, TextModel.target == "welcome_message")
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
            .where(TextModel.chat_id == event.chat.id, TextModel.target == "bye_message")
            .first()
        )
        GOODBYE_MESSAGE = q.text_of if q else "До свидания!"
        q2 = (
            User_listModel
            .select(User_listModel.created_at, User_listModel.message_count)
            .where(User_listModel.chat_id == event.chat.id, User_listModel.user_id == event.old_chat_member.user.id)
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
            .where(User_listModel.chat_id == message.chat.id, User_listModel.user_id == message.from_user.id)
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
            
            # Рассчитываем прогресс до следующего уровня
            exp_for_current = calculate_exp_for_level(current_level)
            exp_for_next = calculate_exp_for_level(current_level + 1)
            exp_in_level = total_exp - exp_for_current
            exp_to_next = exp_for_next - total_exp
            
            # Формируем строку опыта
            if current_level < 20:  # Максимальный уровень
                exp_text = f"⭐ Опыт: {total_exp}/{exp_for_next} (+{exp_to_next} до следующего уровня)"
            else:
                exp_text = f"⭐ Опыт: {total_exp} (максимальный уровень)"
            
            await bot.send_message(
                chat_id=message.chat.id,
                text=(
                    f"📊 <b>Статистика {username}</b>\n\n"
                    f"💬 Сообщений: <b>{q.message_count}</b>\n"
                    f"⏰ С нами: <b>{days} дн., {hours} ч., {minutes} мин.</b>\n"
                    f"📈 Уровень: <b>{current_level}</b>\n"
                    f"🏅 Звание: <b>{user_rank}</b>\n"
                    f"{exp_text}\n"
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
            .insert({
                TextModel.chat_id: message.chat.id,
                TextModel.target: "welcome_message",
                TextModel.text_of: WELCOME_MESSAGE,
                TextModel.edited_at: fn.now()
            })
            .on_conflict(
                conflict_target=[TextModel.chat_id, TextModel.target],
                update={TextModel.text_of: WELCOME_MESSAGE, TextModel.edited_at: fn.now()}
            )
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
            .insert({
                TextModel.chat_id: message.chat.id,
                TextModel.target: "bye_message",
                TextModel.text_of: GOODBYE_MESSAGE,
                TextModel.edited_at: fn.now()
            })
            .on_conflict(
                conflict_target=[TextModel.chat_id, TextModel.target],
                update={TextModel.text_of: GOODBYE_MESSAGE, TextModel.edited_at: fn.now()}
            )
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
                    Button_listModel.chat_id: message.chat.id,
                    Button_listModel.button_name: button_name,
                    Button_listModel.button_link: link,
                })
                .on_conflict(
                    conflict_target=[Button_listModel.chat_id, Button_listModel.button_link],
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
        q = Button_listModel.delete().where(
            Button_listModel.chat_id == message.chat.id,
            Button_listModel.button_name == text
        )
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
                TextModel.chat_id: message.chat.id,
                TextModel.target: "rules",
                TextModel.text_of: rules_text,
                TextModel.edited_at: fn.now()
            })
            .on_conflict(
                conflict_target=[TextModel.chat_id, TextModel.target],
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
            .where(TextModel.chat_id == message.chat.id, TextModel.target == "rules")
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
        query = Button_listModel.select().where(Button_listModel.chat_id == message.chat.id)
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
            .where(SizeModel.chat_id == message.chat.id, SizeModel.user_id == user_id)
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
                    SizeModel.chat_id: message.chat.id,
                    SizeModel.user_id: user_id,
                    SizeModel.size: size,
                    SizeModel.date: today
                })
                .on_conflict(
                    conflict_target=[SizeModel.chat_id, SizeModel.user_id, SizeModel.date],
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
            .where(
                AnekModel.chat_id == message.chat.id,
                AnekModel.user_id == userId
            )
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
                        AnekModel.chat_id: message.chat.id,
                        AnekModel.user_id: userId,
                        AnekModel.count: 1
                    })
                    .on_conflict(
                        conflict_target=[AnekModel.chat_id, AnekModel.user_id],
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
        "<b>🎭 RP-действия:</b>\n"
        "<b>/add_action</b> — Добавить новое RP-действие. Пример: <code>/add_action \"обнять\" \"обнял\"</code>\n"
        "<b>/action_list</b> — Показать список всех RP-действий в чате\n"
        "<b>/del_action</b> — Удалить RP-действие. Пример: <code>/del_action \"обнять\"</code>\n"
        "\n"
        "<b>🎮 Burmalda - Игровая система:</b>\n"
        "• Ежедневно получайте 100 отвальчиков\n"
        "• Играйте в рулетку, слоты и блэкджек за 30 отвальчиков\n"
        "• Каждая игра включает 3 попытки (кроме блэкджека - 1 попытка)\n"
        "• Зарабатывайте отвальчики и бонусный опыт за победы:\n"
        "  - 1 победа: 15 отвальчиков + 30 бонусного опыта\n"
        "  - 2 победы: 35 отвальчиков + 60 бонусного опыта\n"
        "  - 3 победы: 60 отвальчиков + 90 бонусного опыта\n"
        "• Блэкджек: победа = +60 отвальчиков, проигрыш = -30 отвальчиков\n"
        "• Покупайте товары в магазине: снятие предупреждений, обмен отвальчиков на опыт\n"
        "\n"
        "<b>ℹ️ Примечания:</b>\n"
        "• <b>Мут</b> — временно запрещает писать сообщения.\n"
        "• <b>Бан</b> — удаляет пользователя из чата.\n"
        "• Для работы админ-команд бот должен быть админом с нужными правами!\n"
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
        # 5. Очистить все таблицы в базе для этого чата
        try:
            from model import db
            db.execute_sql("DELETE FROM user_list WHERE chat_id = %s;", (chat_id,))
            db.execute_sql("DELETE FROM anek_list WHERE chat_id = %s;", (chat_id,))
            db.execute_sql("DELETE FROM button_list WHERE chat_id = %s;", (chat_id,))
            db.execute_sql("DELETE FROM size_list WHERE chat_id = %s;", (chat_id,))
            db.execute_sql("DELETE FROM ban_list WHERE chat_id = %s;", (chat_id,))
            db.execute_sql("DELETE FROM text WHERE chat_id = %s;", (chat_id,))
            db.execute_sql("DELETE FROM rp_actions WHERE chat_id = %s;", (chat_id,))
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
                User_listModel.chat_id: chat_id,
                User_listModel.user_id: user_id,
                User_listModel.last_visit: fn.now(),
                User_listModel.warn_count: 1,
                User_listModel.rank: 1,  # Начальный уровень
            })
            .on_conflict(
                conflict_target=[User_listModel.chat_id, User_listModel.user_id],
                update={User_listModel.warn_count: User_listModel.warn_count + 1, User_listModel.last_visit: fn.now()}
            )
        )
        q.execute()
        # Получаем новое значение warn_count
        user_record = User_listModel.get(
            User_listModel.chat_id == chat_id,
            User_listModel.user_id == user_id
        )

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
                q = User_listModel.update({User_listModel.warn_count: 0}).where(
                    User_listModel.chat_id == chat_id,
                    User_listModel.user_id == user_id
                )
                updated = q.execute()
                user_record = User_listModel.get_or_none(
                    User_listModel.chat_id == chat_id,
                    User_listModel.user_id == user_id
                )
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
        q = User_listModel.update({User_listModel.warn_count: 0}).where(
            User_listModel.chat_id == message.chat.id,
            User_listModel.user_id == user_id
        )
        updated = q.execute()
        user_record = User_listModel.get_or_none(
            User_listModel.chat_id == message.chat.id,
            User_listModel.user_id == user_id
        )
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

# --- RP-действия ---

@router.message(Command("add_action"))
async def add_rp_action(message: Message, bot: Bot) -> None:
    """Добавляет новое RP-действие в чат."""
    # Отсеиваем привязанный канал и сообщения бота
    if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
        return
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Только администратор может использовать эту команду.")
        return

    try:
        # Улучшенный парсинг аргументов с поддержкой кавычек
        text = message.text.strip()
        logger.info(f"add_rp_action: получен текст: '{text}'")
        
        if not text.startswith('/add_action'):
            logger.info("add_rp_action: текст не начинается с /add_action")
            return
            
        # Убираем команду
        args_text = text[len('/add_action'):].strip()
        logger.info(f"add_rp_action: аргументы после команды: '{args_text}'")
        
        # Парсим аргументы в кавычках
        import re
        quoted_args = re.findall(r'"([^"]*)"', args_text)
        logger.info(f"add_rp_action: найденные аргументы в кавычках: {quoted_args}")
        
        if len(quoted_args) < 2:
            await message.reply(
                "❌ Неверный формат команды!\n\n"
                "Использование: /add_action \"триггер\" \"действие\"\n"
                "Пример: /add_action \"обнять\" \"обнял\"\n\n"
                "⚠️ Обратите внимание на кавычки!"
            )
            return
        
        trigger_word = quoted_args[0].strip()
        action_text = quoted_args[1].strip()
        logger.info(f"add_rp_action: триггер='{trigger_word}', действие='{action_text}'")
        
        # Валидация входных данных
        if not trigger_word or not action_text:
            logger.info("add_rp_action: пустой триггер или действие")
            await message.reply("❌ Триггер и действие не могут быть пустыми.")
            return
            
        if len(trigger_word) > 50:
            logger.info(f"add_rp_action: триггер слишком длинный: {len(trigger_word)}")
            await message.reply("❌ Триггер слишком длинный (максимум 50 символов).")
            return
            
        if len(action_text) > 100:
            logger.info(f"add_rp_action: действие слишком длинное: {len(action_text)}")
            await message.reply("❌ Действие слишком длинное (максимум 100 символов).")
            return
            
        # Проверяем на нежелательный контент
        forbidden_words = ['спам', 'реклама', 'бот', 'admin', 'админ']
        if any(word in trigger_word.lower() for word in forbidden_words):
            logger.info(f"add_rp_action: триггер содержит запрещенные слова: {trigger_word}")
            await message.reply("❌ Триггер содержит запрещенные слова.")
            return
            
        # Нормализуем регистр для поиска
        trigger_word_normalized = trigger_word.lower().strip()
        logger.info(f"add_rp_action: нормализованный триггер: '{trigger_word_normalized}'")
        
        # Проверяем количество действий в чате (лимит 20)
        action_count = RpActionModel.select().where(RpActionModel.chat_id == message.chat.id).count()
        logger.info(f"add_rp_action: текущее количество действий в чате: {action_count}")
        
        if action_count >= 20:
            await message.reply("❌ Достигнут лимит действий в чате (максимум 20). Удалите некоторые действия командой /del_action.")
            return
        
        # Проверяем, не существует ли уже такое действие в этом чате
        existing_action = RpActionModel.get_or_none(
            RpActionModel.chat_id == message.chat.id,
            RpActionModel.trigger_word == trigger_word_normalized
        )
        
        if existing_action:
            logger.info(f"add_rp_action: действие уже существует: {trigger_word}")
            await message.reply(f"❌ Действие с триггером \"{trigger_word}\" уже существует в этом чате.")
            return
        
        # Создаем новое действие
        logger.info(f"add_rp_action: создаю новое действие: {trigger_word_normalized} -> {action_text}")
        (
            RpActionModel
            .insert({
                RpActionModel.chat_id: message.chat.id,
                RpActionModel.trigger_word: trigger_word_normalized,
                RpActionModel.action_text: action_text,
                RpActionModel.created_by: message.from_user.id,
                RpActionModel.created_at: fn.now()
            })
            .on_conflict(
                conflict_target=[RpActionModel.chat_id, RpActionModel.trigger_word],
                update={
                    RpActionModel.action_text: action_text,
                    RpActionModel.created_by: message.from_user.id,
                    RpActionModel.created_at: fn.now()
                }
            )
        ).execute()
        
        # Очищаем кэш для этого чата
        clear_rp_cache(message.chat.id)
        
        await message.reply(
            f"✅ Действие \"{trigger_word}\" успешно добавлено!\n\n"
            f"Теперь можно отвечать на сообщения с текстом \"{trigger_word}\" для активации действия.\n"
            f"Всего действий в чате: {action_count + 1}/20"
        )
        
    except Exception as e:
        logger.error(f"Ошибка в add_rp_action: {e}")
        logger.error(f"Полный текст сообщения: '{message.text}'")
        await message.reply("❌ Произошла ошибка при добавлении действия. Проверьте формат команды.")

@router.message(Command("action_list"))
async def list_rp_actions(message: Message, bot: Bot) -> None:
    """Показывает список всех RP-действий в чате."""
    # Отсеиваем привязанный канал и сообщения бота
    if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
        await message.reply("Команды нельзя использовать от имени канала.")
        return

    try:
        # Получаем все действия для этого чата
        actions = RpActionModel.select().where(RpActionModel.chat_id == message.chat.id).order_by(RpActionModel.trigger_word)
        
        if not actions:
            await message.reply(
                "📝 В этом чате пока нет RP-действий.\n\n"
                "🔧 Администраторы могут добавить их командой:\n"
                "<code>/add_action \"триггер\" \"действие\"</code>\n\n"
                "💡 Пример: <code>/add_action \"обнять\" \"обнял\"</code>",
                parse_mode="HTML"
            )
            return
        
        # Формируем список действий
        action_list = []
        for i, action in enumerate(actions, 1):
            action_list.append(f"{i}. <b>{action.trigger_word}</b> → {action.action_text}")
        
        response_text = (
            f"🎭 <b>Список RP-действий в чате ({len(actions)}/20):</b>\n\n" +
            "\n".join(action_list) + 
            "\n\n💡 <b>Как использовать:</b>\n"
            "Ответьте на сообщение пользователя с текстом действия для активации.\n\n"
            "📝 <b>Пример:</b>\n"
            "Ответить \"обнять\" на сообщение → @Вы обняли @Пользователь"
        )
        
        await message.reply(response_text, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка в list_rp_actions: {e}")
        await message.reply("❌ Произошла ошибка при получении списка действий.")

@router.message(Command("del_action"))
async def delete_rp_action(message: Message, bot: Bot) -> None:
    """Удаляет RP-действие из чата."""
    # Отсеиваем привязанный канал и сообщения бота
    if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
        return
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Только администратор может использовать эту команду.")
        return

    try:
        # Улучшенный парсинг аргументов
        text = message.text.strip()
        if not text.startswith('/del_action'):
            return
            
        # Убираем команду
        args_text = text[len('/del_action'):].strip()
        
        # Парсим аргумент в кавычках
        import re
        quoted_args = re.findall(r'"([^"]*)"', args_text)
        
        if len(quoted_args) < 1:
            await message.reply(
                "❌ Неверный формат команды!\n\n"
                "Использование: /del_action \"триггер\"\n"
                "Пример: /del_action \"обнять\"\n\n"
                "⚠️ Обратите внимание на кавычки!"
            )
            return
        
        trigger_word = quoted_args[0].strip()
        
        if not trigger_word:
            await message.reply("❌ Триггер не может быть пустым.")
            return
        
        # Нормализуем регистр для поиска
        trigger_word_normalized = trigger_word.lower().strip()
        
        # Удаляем действие
        deleted_count = RpActionModel.delete().where(
            RpActionModel.chat_id == message.chat.id,
            RpActionModel.trigger_word == trigger_word_normalized
        ).execute()
        
        if deleted_count > 0:
            # Получаем обновленное количество действий
            action_count = RpActionModel.select().where(RpActionModel.chat_id == message.chat.id).count()
            
            # Очищаем кэш для этого чата
            clear_rp_cache(message.chat.id)
            
            await message.reply(
                f"✅ Действие \"{trigger_word}\" удалено из чата.\n"
                f"Осталось действий: {action_count}/20"
            )
        else:
            await message.reply(f"❌ Действие \"{trigger_word}\" не найдено в этом чате.")
        
    except Exception as e:
        logger.error(f"Ошибка в delete_rp_action: {e}")
        await message.reply("❌ Произошла ошибка при удалении действия. Проверьте формат команды.")

@router.message(Command("clear_rp_cache"))
async def clear_rp_cache_command(message: Message, bot: Bot) -> None:
    """Очищает кэш RP-действий для чата (только для админов)."""
    # Отсеиваем привязанный канал и сообщения бота
    if message.chat.type == "channel" or (message.from_user and message.from_user.is_bot):
        return
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Только администратор может использовать эту команду.")
        return

    try:
        clear_rp_cache(message.chat.id)
        await message.reply("✅ Кэш RP-действий очищен для этого чата.")
    except Exception as e:
        logger.error(f"Ошибка в clear_rp_cache_command: {e}")
        await message.reply("❌ Произошла ошибка при очистке кэша.")

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
        chat_id = message.chat.id
        username = message.from_user.username if message.from_user.username is not None else message.from_user.first_name
        
        # Проверяем и выдаем ежедневные кредиты
        daily_credits = await burmalda_game.check_and_give_daily_credits(user_id, chat_id)
        
        # Создаем главное меню
        text, markup = burmalda_game.create_main_menu(user_id, chat_id)
        
        # Добавляем информацию о ежедневных кредитах
        if daily_credits > 0:
            text += f"\n\n🎁 <b>Получено {daily_credits} ежедневных кредитов!</b>"
        
        await message.reply(text, reply_markup=markup, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка в команде burmalda для user_id {message.from_user.id}: {e}")
        await message.reply("❌ Произошла ошибка при открытии игровой системы.")

@router.callback_query(F.data.startswith("burmalda_finish_"))
async def burmalda_finish_callback(call: CallbackQuery, bot: Bot) -> None:
    # Проверяем, что callback отправил тот же пользователь
    user_id = int(call.data.split("_")[2])
    if call.from_user.id != user_id:
        await call.answer("❌ Это не ваша игра! Вызовите своё меню через /burmalda", show_alert=True)
        return
    await finish_burmalda_game(call, bot)

@router.callback_query(F.data.startswith("burmalda_transfer_"))
async def burmalda_transfer_init(call: CallbackQuery, bot: Bot) -> None:
    user_id = int(call.data.split("_")[-1])
    if call.from_user.id != user_id:
        await call.answer("❌ Это не ваше меню!", show_alert=True)
        return
    chat_id = call.message.chat.id
    # Сохраняем состояние ожидания ответа
    TRANSFER_CACHE[user_id] = {"step": "wait_reply", "chat_id": chat_id}
    msg = await bot.send_message(
        chat_id=chat_id,
        text=(
            "✉️ Ответьте на это сообщение тегом пользователя и количеством отвальчиков для передачи.\n"
            "Пример: @username 100"
        )
    )
    TRANSFER_CACHE[user_id]["msg_id"] = msg.message_id
    await call.answer()

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
        chat_id = call.message.chat.id
        
        if action == "main":
            # Главное меню
            user_id = int(data[2])
            
            # Проверяем, что callback отправил тот же пользователь
            if call.from_user.id != user_id:
                await call.answer("❌ Это не ваше меню! Вызовите своё меню через /burmalda", show_alert=True)
                return
                
            text, markup = burmalda_game.create_main_menu(user_id, chat_id)
            await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
            
        elif action == "shop":
            # Магазин
            user_id = int(data[2])
            
            # Проверяем, что callback отправил тот же пользователь
            if call.from_user.id != user_id:
                await call.answer("❌ Это не ваше меню! Вызовите своё меню через /burmalda", show_alert=True)
                return
                
            text, markup = burmalda_game.create_shop_menu(user_id, chat_id)
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
                await call.answer("❌ Это не ваша игра! Вызовите своё меню через /burmalda", show_alert=True)
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
                credits = burmalda_game.get_user_credits(user_id, chat_id)
                if credits < GAME_COST:
                    await call.answer(f"❌ Недостаточно отвальчиков! Нужно: {GAME_COST}, у вас: {credits}", show_alert=True)
                    return
                    
                # Тратим кредиты за всю игру
                if not burmalda_game.spend_credits(user_id, chat_id, GAME_COST):
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
                await call.answer("❌ Это не ваше меню! Вызовите своё меню через /burmalda", show_alert=True)
                return
                
            q = (
                User_listModel
                .select(User_listModel.warn_count)
                .where(
                    User_listModel.chat_id == call.message.chat.id,
                    User_listModel.user_id == user_id
                )
                .first()
            )
            
            if not q or q.warn_count == 0:
                await call.answer("❌ У вас нет предупреждений для снятия", show_alert=True)
                return
                
            points = burmalda_game.get_user_points(user_id, chat_id)
            if points < WARN_REMOVAL_COST:
                await call.answer(f"❌ Недостаточно отвальчиков! Нужно: {WARN_REMOVAL_COST}, у вас: {points}", show_alert=True)
                return
                
            # Снимаем предупреждение и тратим отвальчики
            (
                User_listModel
                .update({
                    User_listModel.warn_count: User_listModel.warn_count - 1
                })
                .where(
                    User_listModel.chat_id == call.message.chat.id,
                    User_listModel.user_id == user_id
                )
            ).execute()
            
            burmalda_game.spend_points(user_id, chat_id, WARN_REMOVAL_COST)
            
            await call.answer(f"✅ Предупреждение снято! Потрачено {WARN_REMOVAL_COST} отвальчиков", show_alert=True)
            
            # Обновляем меню магазина
            text, markup = burmalda_game.create_shop_menu(user_id, chat_id)
            await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
            
        elif action == "exchange":
            # Обмен очков на опыт
            if len(data) < 4 or data[-2] != "exp":
                await call.answer("❌ Неверный формат данных", show_alert=True)
                return
            user_id = int(data[-1])
            # Проверяем, что callback отправил тот же пользователь
            if call.from_user.id != user_id:
                await call.answer("❌ Это не ваше меню! Вызовите своё меню через /burmalda", show_alert=True)
                return
            q = (
                User_listModel
                .select(User_listModel.rank)
                .where(
                    User_listModel.chat_id == call.message.chat.id,
                    User_listModel.user_id == user_id
                )
                .first()
            )
            if not q:
                await call.answer("❌ Пользователь не найден", show_alert=True)
                return
            points = burmalda_game.get_user_points(user_id, chat_id)
            if points < 100:
                await call.answer(f"❌ Недостаточно отвальчиков! Нужно: 100, у вас: {points}", show_alert=True)
                return
            # Рассчитываем опыт за каждые 100 отвальчиков
            commission = burmalda_game.get_commission_rate(q.rank)
            exp_gained = int(100 * (1 - commission))
            # Тратим отвальчики и начисляем опыт
            if not burmalda_game.spend_points(user_id, chat_id, 100):
                await call.answer(f"❌ Не удалось списать отвальчики. Возможно, их недостаточно.", show_alert=True)
                return
            await award_exp_and_check_level_up(user_id, exp_gained, 0, call.from_user.first_name, call.message, bot, call.message.chat.id)
            await call.answer(f"✅ Получено {exp_gained} опыта за 100 отвальчиков! Комиссия: {commission*100:.0f}%", show_alert=True)
            # Обновляем меню магазина
            text, markup = burmalda_game.create_shop_menu(user_id, chat_id)
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
        chat_id = call.message.chat.id
        
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        
        if game_type == "slot":
            result = await burmalda_game.play_slot_game(user_id, chat_id)
            if result.won:
                game_state["wins"] += 1
                
            # Рассчитываем текущие выигрыши в отвальчиках
            current_wins = game_state["wins"]
            current_credits_earned = ATTEMPT_REWARDS.get(current_wins, 0)
            
            # Добавляем информацию о попытках и выигрышах
            attempts_info = f"\n\n🎯 Попытка {game_state['attempts']}/{GAME_ATTEMPTS}"
            attempts_info += f"\n🏆 Победы: {current_wins}"
            attempts_info += f"\n💰 Выигрыш: {current_credits_earned} отвальчиков"
            
            if game_state["attempts"] < GAME_ATTEMPTS:
                # Добавляем кнопку для следующей попытки
                builder.button(text="🎰 Следующая попытка", callback_data=f"burmalda_game_slot_{user_id}")
                builder.button(text="🏁 Завершить игру", callback_data=f"burmalda_finish_{user_id}")
                builder.adjust(2)
            else:
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
            result = await burmalda_game.play_roulette_game(user_id, chat_id)
            if result.won:
                game_state["wins"] += 1
                
            # Рассчитываем текущие выигрыши в отвальчиках
            current_wins = game_state["wins"]
            current_credits_earned = ATTEMPT_REWARDS.get(current_wins, 0)
            
            # Добавляем информацию о попытках и выигрышах
            attempts_info = f"\n\n🎯 Попытка {game_state['attempts']}/{GAME_ATTEMPTS}"
            attempts_info += f"\n🏆 Победы: {current_wins}"
            attempts_info += f"\n💰 Выигрыш: {current_credits_earned} отвальчиков"
            
            if game_state["attempts"] < GAME_ATTEMPTS:
                # Добавляем кнопку для следующей попытки
                builder.button(text="🎲 Следующая попытка", callback_data=f"burmalda_game_roulette_{user_id}")
                builder.button(text="🏁 Завершить игру", callback_data=f"burmalda_finish_{user_id}")
                builder.adjust(2)
            else:
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
        chat_id = call.message.chat.id
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
            burmalda_game.add_points(user_id, chat_id, points_earned)
        # Начисляем бонусный опыт за победы
        if bonus_exp_earned > 0:
            logger.info(f"[finish_burmalda_game] Добавляю бонусный опыт: {bonus_exp_earned}")
            burmalda_game.add_bonus_exp(user_id, chat_id, bonus_exp_earned)
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
            text, markup = burmalda_game.create_main_menu(user_id, chat_id)
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
                User_listModel.chat_id: message.chat.id,
                User_listModel.user_id: user_id,
                User_listModel.message_count: 1,
                User_listModel.last_visit: fn.now(),
                User_listModel.rank: 1,  # Начальный уровень
                User_listModel.credits: 0,  # Начальные отвальчики
            })
            .on_conflict(
                conflict_target=[User_listModel.chat_id, User_listModel.user_id],
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

        # Проверяем RP-действия (только для ответов на сообщения)
        if message.reply_to_message and message.text:
            await process_rp_action(message, bot)

        username = message.from_user.username if message.from_user.username is not None else message.from_user.first_name
        total_exp_to_award = 0
        level_exp_to_award = 0
        bonus_exp_to_award = 0

        # Проверяем винстрик
        is_new_day, streak = check_visit_streak(user_id, message.chat.id)
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
            await award_exp_and_check_level_up(user_id, level_exp_to_award, bonus_exp_to_award, username, message, bot, message.chat.id)

    except Exception as e:
        logger.error(f"Ошибка в handle_all_messages для user_id {message.from_user.id}: {e}")

@router.callback_query(F.data.startswith("blackjack_hit_"))
async def blackjack_hit_callback(call: CallbackQuery, bot: Bot) -> None:
    # Проверяем, что callback отправил тот же пользователь
    user_id = int(call.data.split('_')[-1])
    if call.from_user.id != user_id:
        await call.answer("❌ Это не ваша игра! Вызовите своё меню через /burmalda", show_alert=True)
        return
    await process_blackjack_hit(call, bot)

@router.callback_query(F.data.startswith("blackjack_stand_"))
async def blackjack_stand_callback(call: CallbackQuery, bot: Bot) -> None:
    # Проверяем, что callback отправил тот же пользователь
    user_id = int(call.data.split('_')[-1])
    if call.from_user.id != user_id:
        await call.answer("❌ Это не ваша игра! Вызовите своё меню через /burmalda", show_alert=True)
        return
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
    
    # Определяем результат и награды
    if player_bust:
        result = "❌ Перебор! Вы проиграли."
        won = False
        credits_change = -30  # Теряем 30 отвальчиков
    elif dealer_score > 21 or player_score > dealer_score:
        result = "🎉 Победа!"
        won = True
        credits_change = 60  # Получаем 60 отвальчиков
    elif player_score == dealer_score:
        result = "🤝 Ничья!"
        won = False
        credits_change = 0  # Ничья - ничего не теряем и не получаем
    else:
        result = "❌ Проигрыш."
        won = False
        credits_change = -30  # Теряем 30 отвальчиков
    
    # Применяем изменения к отвальчикам
    if credits_change != 0:
        if credits_change > 0:
            burmalda_game.add_points(user_id, call.message.chat.id, credits_change)
        else:
            # Для проигрыша просто не начисляем отвальчики (они уже потрачены при начале игры)
            pass
    
    # Формируем сообщение с информацией о выигрыше
    credits_text = ""
    if credits_change > 0:
        credits_text = f"\n💰 Выигрыш: +{credits_change} отвальчиков"
    elif credits_change < 0:
        credits_text = f"\n💸 Проигрыш: {credits_change} отвальчиков"
    else:
        credits_text = f"\n🤝 Ничья: 0 отвальчиков"
    
    text = (
        f"🃏 <b>Блэкджек</b>\n\n"
        f"Ваши карты: {player_cards_str}\n"
        f"Ваши очки: <b>{player_score}</b>\n\n"
        f"Карты дилера: {dealer_cards_str}\n"
        f"Очки дилера: <b>{dealer_score}</b>\n\n"
        f"{result}{credits_text}"
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

# Кэш для RP-действий (chat_id -> {trigger_word: action_text})
RP_ACTIONS_CACHE = {}
RP_CACHE_TIMEOUT = 300  # 5 минут

def clear_rp_cache(chat_id: int) -> None:
    """Очищает кэш RP-действий для указанного чата"""
    if chat_id in RP_ACTIONS_CACHE:
        del RP_ACTIONS_CACHE[chat_id]
        logger.debug(f"Кэш RP-действий очищен для чата {chat_id}")

async def process_rp_action(message: Message, bot: Bot) -> None:
    """
    Обрабатывает RP-действия при ответе на сообщения.
    Формат: пользователь отвечает на сообщение с текстом действия
    """
    try:
        # Защита от спама (3 секунды между использованиями)
        user_id = message.from_user.id
        current_time = datetime.now().timestamp()
        
        if hasattr(process_rp_action, 'last_usage') and user_id in process_rp_action.last_usage:
            if current_time - process_rp_action.last_usage[user_id] < 3:
                await message.reply("⏰ Подождите немного перед следующим RP-действием!")
                return
        
        # Инициализируем словарь для отслеживания использования
        if not hasattr(process_rp_action, 'last_usage'):
            process_rp_action.last_usage = {}
        
        process_rp_action.last_usage[user_id] = current_time
        
        # Получаем текст сообщения и разбиваем на строки
        text_lines = message.text.strip().split('\n')
        if not text_lines:
            return
            
        trigger_word = text_lines[0].strip().lower()
        
        # Проверяем кэш
        chat_id = message.chat.id
        current_time = datetime.now().timestamp()
        
        if chat_id not in RP_ACTIONS_CACHE or current_time - RP_ACTIONS_CACHE[chat_id]['timestamp'] > RP_CACHE_TIMEOUT:
            # Обновляем кэш
            actions = RpActionModel.select().where(RpActionModel.chat_id == chat_id)
            actions_dict = {action.trigger_word: action.action_text for action in actions}
            RP_ACTIONS_CACHE[chat_id] = {
                'actions': actions_dict,
                'timestamp': current_time
            }
        
        # Ищем действие в кэше
        action_text = RP_ACTIONS_CACHE[chat_id]['actions'].get(trigger_word)
        
        if not action_text:
            return  # Действие не найдено, ничего не делаем
        
        # Получаем информацию о пользователях
        actor_username = message.from_user.username if message.from_user.username else message.from_user.first_name
        target_username = message.reply_to_message.from_user.username if message.reply_to_message.from_user.username else message.reply_to_message.from_user.first_name
        
        # Проверяем, что пользователь не отвечает сам на себя
        if message.from_user.id == message.reply_to_message.from_user.id:
            await message.reply("❌ Нельзя использовать RP-действия на своих собственных сообщениях!")
            return
        
        # Проверяем, что цель не бот
        if message.reply_to_message.from_user.is_bot:
            await message.reply("❌ Нельзя использовать RP-действия на сообщениях ботов!")
            return
        
        # Формируем текст действия
        result_action_text = action_text
        
        # Если есть дополнительные строки в сообщении, добавляем их как "со словами"
        additional_text = ""
        if len(text_lines) > 1:
            additional_text = " ".join(text_lines[1:]).strip()
            if additional_text:
                # Ограничиваем длину дополнительного текста
                if len(additional_text) > 200:
                    additional_text = additional_text[:197] + "..."
                result_action_text += f" со словами: {additional_text}"
        
        # Формируем финальное сообщение
        result_message = f"@{actor_username} {result_action_text} @{target_username}"
        
        # Проверяем общую длину сообщения
        if len(result_message) > 4096:
            await message.reply("❌ Сообщение слишком длинное! Сократите дополнительный текст.")
            return
        
        # Отправляем сообщение как ответ на исходное сообщение
        await bot.send_message(
            chat_id=message.chat.id,
            text=result_message,
            reply_to_message_id=message.reply_to_message.message_id
        )
        
        # Удаляем исходное сообщение с действием
        try:
            await message.delete()
        except Exception as e:
            logger.error(f"Не удалось удалить сообщение с RP-действием: {e}")
            
    except Exception as e:
        logger.error(f"Ошибка при обработке RP-действия: {e}")

# --- Кэш для передачи очков ---
TRANSFER_CACHE = {}  # user_id: {"step": str, ...}

@router.callback_query(F.data.startswith("burmalda_transfer_"))
async def burmalda_transfer_init(call: CallbackQuery, bot: Bot) -> None:
    user_id = int(call.data.split("_")[-1])
    if call.from_user.id != user_id:
        await call.answer("❌ Это не ваше меню!", show_alert=True)
        return
    chat_id = call.message.chat.id
    # Сохраняем состояние ожидания ответа
    TRANSFER_CACHE[user_id] = {"step": "wait_reply", "chat_id": chat_id}
    msg = await bot.send_message(
        chat_id=chat_id,
        text=(
            "✉️ Ответьте на это сообщение тегом пользователя и количеством отвальчиков для передачи.\n"
            "Пример: @username 100"
        )
    )
    TRANSFER_CACHE[user_id]["msg_id"] = msg.message_id
    await call.answer()

@router.message()
async def handle_transfer_reply(message: Message, bot: Bot) -> None:
    user_id = message.from_user.id
    import json
    logger.info(f"[TRANSFER] user_id={user_id}, text={message.text}, entities={message.entities}, reply_to_message_id={getattr(message.reply_to_message, 'message_id', None)}")
    if user_id not in TRANSFER_CACHE:
        logger.info(f"[TRANSFER] user_id {user_id} not in TRANSFER_CACHE")
        return  # Не в процессе передачи
    state = TRANSFER_CACHE[user_id]
    logger.info(f"[TRANSFER] state={state}")
    # Отправляем debug-информацию в чат для диагностики
    debug_info = {
        'user_id': user_id,
        'text': message.text,
        'entities': str(message.entities),
        'reply_to_message_id': getattr(message.reply_to_message, 'message_id', None),
        'expected_msg_id': state.get('msg_id'),
        'state': state
    }
    await message.reply(f"DEBUG: {json.dumps(debug_info, ensure_ascii=False)}")
    if state.get("step") != "wait_reply":
        logger.info(f"[TRANSFER] state.step != wait_reply")
        return
    # Проверяем, что это reply на сообщение бота
    if not message.reply_to_message or message.reply_to_message.message_id != state.get("msg_id"):
        logger.info(f"[TRANSFER] reply_to_message check failed")
        return
    # Парсим тег и количество
    parts = message.text.strip().split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.reply("❌ Формат: @username 100")
        return
    tag, amount_str = parts
    amount = int(amount_str)
    if amount <= 0:
        await message.reply("❌ Количество должно быть больше 0")
        return
    # Получаем user_id по тегу
    try:
        entities = message.entities or []
        to_user_id = None
        for ent in entities:
            if ent.type == "mention":
                username = tag.lstrip("@")
                # Получаем id через get_chat_member
                try:
                    member = await bot.get_chat_member(message.chat.id, username)
                    to_user_id = member.user.id
                except Exception:
                    pass
            elif ent.type == "text_mention":
                to_user_id = ent.user.id
        if not to_user_id:
            # Попробуем через username
            if tag.startswith("@"):
                try:
                    member = await bot.get_chat_member(message.chat.id, tag[1:])
                    to_user_id = member.user.id
                except Exception:
                    pass
        if not to_user_id:
            await message.reply("❌ Не удалось определить пользователя по тегу")
            return
    except Exception:
        await message.reply("❌ Ошибка при определении пользователя")
        return
    if to_user_id == user_id:
        await message.reply("❌ Нельзя переводить отвальчики самому себе")
        return
    # Проверяем баланс
    if not burmalda_game.can_transfer_points(user_id, message.chat.id, amount):
        await message.reply("❌ Недостаточно отвальчиков для перевода")
        return
    # Сохраняем параметры перевода
    state.update({"step": "wait_confirm", "to_user_id": to_user_id, "amount": amount})
    # Получаем имя получателя
    try:
        member = await bot.get_chat_member(message.chat.id, to_user_id)
        to_name = member.user.username or member.user.first_name
    except Exception:
        to_name = str(to_user_id)
    # Кнопки подтверждения
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=f"transfer_confirm_{user_id}")
    builder.button(text="❌ Отмена", callback_data=f"transfer_cancel_{user_id}")
    builder.adjust(2)
    reply_msg = await message.reply(
        f"Передать <b>{amount}</b> отвальчиков пользователю @{to_name}?",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    state["confirm_msg_id"] = reply_msg.message_id
    # --- Таймаут подтверждения ---
    import asyncio
    async def transfer_timeout():
        await asyncio.sleep(30)
        # Если перевод не подтвержден/не отменен
        if user_id in TRANSFER_CACHE and TRANSFER_CACHE[user_id].get("step") == "wait_confirm":
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=reply_msg.message_id,
                    text="⏰ Время на подтверждение истекло"
                )
            except Exception:
                pass
            del TRANSFER_CACHE[user_id]
    timeout_task = asyncio.create_task(transfer_timeout())
    state["timeout_task"] = timeout_task

@router.callback_query(F.data.startswith("transfer_confirm_"))
async def transfer_confirm(call: CallbackQuery, bot: Bot) -> None:
    user_id = int(call.data.split("_")[-1])
    state = TRANSFER_CACHE.get(user_id)
    if not state or state.get("step") != "wait_confirm":
        await call.answer("❌ Нет активного перевода", show_alert=True)
        return
    # Отменяем таймаут
    if "timeout_task" in state:
        state["timeout_task"].cancel()
    chat_id = state["chat_id"]
    to_user_id = state["to_user_id"]
    amount = state["amount"]
    # Повторная проверка баланса
    if not burmalda_game.can_transfer_points(user_id, chat_id, amount):
        await call.answer("❌ Недостаточно отвальчиков", show_alert=True)
        del TRANSFER_CACHE[user_id]
        return
    # Переводим
    if not burmalda_game.transfer_points(user_id, to_user_id, chat_id, amount):
        await call.answer("❌ Ошибка при переводе", show_alert=True)
        del TRANSFER_CACHE[user_id]
        return
    # Начисляем опыт отправителю
    await award_exp_and_check_level_up(user_id, amount, 0, call.from_user.first_name, None, bot, chat_id)
    # Уведомляем
    try:
        member = await bot.get_chat_member(chat_id, to_user_id)
        to_name = member.user.username or member.user.first_name
    except Exception:
        to_name = str(to_user_id)
    await call.message.edit_text(
        f"✅ <b>Успешно передано {amount} отвальчиков пользователю @{to_name}</b>",
        parse_mode="HTML"
    )
    del TRANSFER_CACHE[user_id]
    await call.answer()

@router.callback_query(F.data.startswith("transfer_cancel_"))
async def transfer_cancel(call: CallbackQuery, bot: Bot) -> None:
    user_id = int(call.data.split("_")[-1])
    state = TRANSFER_CACHE.get(user_id)
    if state and "timeout_task" in state:
        state["timeout_task"].cancel()
    if user_id in TRANSFER_CACHE:
        del TRANSFER_CACHE[user_id]
    await call.message.edit_text("❌ Перевод отменён")
    await call.answer()