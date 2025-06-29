import asyncio
from datetime import datetime, timezone, timedelta
from itertools import count
from typing import Dict, Tuple
import logging
import pytz
import random
from functools import lru_cache
from pathlib import Path

from peewee import fn
from aiogram import Bot

from model import AnekModel, User_listModel, SizeModel

logger = logging.getLogger(__name__)

# Константы для системы уровней
BASE_EXP = 150
BASE_DIFF = 250
DIFF_INCREASE = 100
MAX_LEVEL = 20
MAX_EXP = 22000

# Кэш для званий
RANKS_CACHE: Dict[int, str] = {}

# Кэш для проверки админов
ADMIN_CACHE: Dict[Tuple[int, int], bool] = {}
ADMIN_CACHE_TIMEOUT = 300  # 5 минут

@lru_cache(maxsize=1000)
def quota_check(userid: int, qcount: int) -> bool:
    """
    Проверяет, превысил ли пользователь дневной лимит анекдотов.
    Если лимит превышен и прошёл день с последнего запроса (по МСК), сбрасывает счётчик.
    Возвращает True, если пользователь может получить анекдот, иначе False.
    
    Args:
        userid (int): ID пользователя
        qcount (int): Текущее количество запросов
        
    Returns:
        bool: True если можно получить анекдот, False если превышен лимит
    """
    try:
        q = (
            AnekModel.select(AnekModel.created_at)
            .where(AnekModel.user_id == userid)
            .first()
        )
        if not q or not hasattr(q, 'created_at'):
            return True
            
        recent_time = q.created_at
        MSK = pytz.timezone("Europe/Moscow")
        # Приводим к МСК
        if recent_time.tzinfo is None:
            recent_time = recent_time.replace(tzinfo=timezone.utc)
        recent_time_msk = recent_time.astimezone(MSK).date()
        now_msk = datetime.now(MSK).date()
        
        if now_msk > recent_time_msk:
            q2 = (
                AnekModel
                .update({AnekModel.count: 0})
                .where(AnekModel.user_id == userid)
            )
            q2.execute()
            return True
            
        return qcount < 3
    except Exception as e:
        logger.error(f"Ошибка в quota_check для userid {userid}: {e}")
        return False

@lru_cache(maxsize=1000)
def calculate_level(exp: int) -> int:
    """
    Рассчитывает уровень пользователя на основе опыта.
    Формула учитывает увеличивающуюся разницу между уровнями.
    
    Args:
        exp (int): Количество опыта пользователя
        
    Returns:
        int: Уровень пользователя (1-20)
    """
    if exp < BASE_EXP:
        logger.info(f"DEBUG: calculate_level({exp}) = 1 (меньше BASE_EXP={BASE_EXP})")
        return 1
    if exp >= MAX_EXP:
        logger.info(f"DEBUG: calculate_level({exp}) = {MAX_LEVEL} (больше или равно MAX_EXP={MAX_EXP})")
        return MAX_LEVEL
        
    try:
        a = DIFF_INCREASE / 2
        b = BASE_DIFF - DIFF_INCREASE
        c = -(exp + BASE_DIFF - BASE_EXP)
        
        discriminant = b**2 - 4*a*c
        level = int((-b + (discriminant)**0.5) / (2*a))
        
        result = min(max(level, 1), MAX_LEVEL)
        logger.info(f"DEBUG: calculate_level({exp}) = {result} (a={a}, b={b}, c={c}, discriminant={discriminant})")
        return result
    except Exception as e:
        logger.error(f"Ошибка в calculate_level для exp {exp}: {e}")
        return 1

@lru_cache(maxsize=1000)
def calculate_exp_for_level(level: int) -> int:
    """
    Рассчитывает требуемый опыт для достижения указанного уровня.
    
    Args:
        level (int): Целевой уровень (1-20)
        
    Returns:
        int: Требуемое количество опыта
    """
    if level < 1:
        return 0
    if level > MAX_LEVEL:
        return MAX_EXP
        
    try:
        result = int(BASE_EXP + BASE_DIFF*(level-1) + (DIFF_INCREASE/2)*(level-1)*(level-2))
        logger.info(f"DEBUG: calculate_exp_for_level({level}) = {result}")
        return result
    except Exception as e:
        logger.error(f"Ошибка в calculate_exp_for_level для level {level}: {e}")
        return 0

@lru_cache(maxsize=1000)
def calculate_messages_for_level(level: int) -> int:
    """
    Рассчитывает требуемое количество сообщений для достижения указанного уровня.
    
    Args:
        level (int): Целевой уровень (1-20)
        
    Returns:
        int: Требуемое количество сообщений
    """
    if level == 1:
        return 150
    try:
        return 150 + (level - 1) * 250 + (level - 1) * (level - 2) * 50
    except Exception as e:
        logger.error(f"Ошибка в calculate_messages_for_level для level {level}: {e}")
        return 0

def get_user_rank(level: int) -> str:
    """
    Возвращает звание пользователя на основе его уровня.
    
    Args:
        level (int): Уровень пользователя
        
    Returns:
        str: Звание пользователя
    """
    try:
        # Проверяем кэш
        if level in RANKS_CACHE:
            return RANKS_CACHE[level]
            
        ranks_file = Path("ranks.txt")
        if not ranks_file.exists():
            logger.error("Файл ranks.txt не найден")
            return "Неизвестное звание"
            
        with ranks_file.open("r", encoding="utf-8") as file:
            ranks = [line.strip() for line in file if line.strip()]
        
        if not ranks:
            return "Неизвестное звание"
            
        # Убираем номер уровня из строки
        ranks = [rank.split(". ", 1)[1] if ". " in rank else rank for rank in ranks]
        
        # Если уровень больше максимального, возвращаем последнее звание
        if level > MAX_LEVEL:
            rank = ranks[-1]
        else:
            rank = ranks[level - 1]
            
        # Сохраняем в кэш
        RANKS_CACHE[level] = rank
        return rank
    except Exception as e:
        logger.error(f"Ошибка при получении звания для уровня {level}: {e}")
        return "Неизвестное звание"

def check_visit_streak(user_id: int) -> Tuple[bool, int]:
    """
    Проверяет и обновляет винстрик посещений пользователя.
    Returns: (is_new_day, streak)
    """
    try:
        now = datetime.now(timezone.utc)
        user = User_listModel.get_or_none(User_listModel.user_id == user_id)
        if user is None:
            User_listModel.insert({
                User_listModel.created_at: fn.now(),
                User_listModel.user_id: user_id,
                User_listModel.last_visit: fn.now(),
                User_listModel.visit_streak: 1,
                User_listModel.rank: 1  # Начальный уровень
            }).execute()
            return True, 1

        last_visit = user.last_visit
        if last_visit is None or (now.date() - last_visit.date()).days > 1:
            # streak сбрасывается
            User_listModel.update({
                User_listModel.last_visit: fn.now(),
                User_listModel.visit_streak: 1
            }).where(User_listModel.user_id == user_id).execute()
            return True, 1
        elif last_visit.date() == now.date():
            # streak не увеличивается
            return False, user.visit_streak
        elif last_visit.date() == (now - timedelta(days=1)).date():
            # streak увеличивается
            User_listModel.update({
                User_listModel.last_visit: fn.now(),
                User_listModel.visit_streak: user.visit_streak + 1
            }).where(User_listModel.user_id == user_id).execute()
            return True, user.visit_streak + 1
        else:
            # fallback
            return False, user.visit_streak
    except Exception as e:
        logger.error(f"Ошибка в check_visit_streak для user_id {user_id}: {e}")
        return False, 0

async def award_size_top_exp(bot, chat_id: int) -> None:
    """
    Начисляет опыт за места в таблице размеров.
    
    Args:
        bot: Экземпляр бота
        chat_id (int): ID чата
    """
    try:
        moscow_tz = pytz.timezone('Europe/Moscow')
        today = datetime.now(moscow_tz).date()
        
        # Получаем топ-3 за сегодня
        query = (
            SizeModel
            .select(SizeModel.user_id, SizeModel.size)
            .where(SizeModel.date == today)
            .order_by(SizeModel.size.desc())
            .limit(3)
        )
        results = list(query)
        
        if not results:
            return
            
        # Награды за места
        rewards = {
            0: 200,  # 1 место
            1: 100,  # 2 место
            2: 50    # 3 место
        }
        
        # Начисляем опыт
        for idx, result in enumerate(results):
            if idx in rewards:
                try:
                    member = await bot.get_chat_member(chat_id, result.user_id)
                    username = member.user.username if member.user.username is not None else member.user.first_name
                    place = idx + 1
                    
                    # Начисляем опыт с проверкой повышения уровня
                    await award_exp_and_check_level_up(result.user_id, 0, rewards[idx], username, None, bot)
                    
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"🏆 <b>{username}</b> получает <b>{rewards[idx]}</b> бонусного опыта за {place}-е место в таблице размеров!",
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке сообщения о награде для user_id {result.user_id}: {e}")
                        
    except Exception as e:
        logger.error(f"Ошибка при начислении опыта за таблицу размеров: {e}")


async def kick_for_unactive(bot, chat_id: int) -> None:
    """
    Кикает пользователей за неактив более 30 дней.
    Args:
        bot: Экземпляр бота
        chat_id (int): ID чата
    """
    try:
        moscow_tz = pytz.timezone('Europe/Moscow')
        now = datetime.now(moscow_tz)
        thirty_days_ago = now - timedelta(days=30)

        # Получаем всех пользователей с их последним посещением
        query = (
            User_listModel
            .select(User_listModel.user_id, User_listModel.last_visit)
            .where(User_listModel.last_visit.is_null(False))  # Только пользователи с записью о посещении
        )
        results = list(query)

        if not results:
            logger.info("Нет пользователей для проверки на неактивность")
            return

        kicked_count = 0
        for result in results:
            try:
                # Проверяем, является ли пользователь администратором
                if await is_admin(bot, chat_id, result.user_id):
                    continue
                
                # Проверяем, прошло ли более 30 дней с последнего посещения
                last_visit = result.last_visit
                if last_visit.tzinfo is None:
                    last_visit = last_visit.replace(tzinfo=timezone.utc)
                last_visit_msk = last_visit.astimezone(moscow_tz)
                
                if last_visit_msk < thirty_days_ago:
                    # Кикаем пользователя
                    try:
                        member = await bot.get_chat_member(chat_id, result.user_id)
                        username = member.user.username if member.user.username else member.user.first_name
                        
                        # Баним и сразу разбаниваем (это кикает пользователя)
                        await bot.ban_chat_member(chat_id, result.user_id)
                        await bot.unban_chat_member(chat_id, result.user_id)
                        
                        kicked_count += 1
                        logger.info(f"Пользователь {username} (ID: {result.user_id}) кикнут за неактивность более 30 дней")
                        
                        # Небольшая пауза между киками
                        await asyncio.sleep(1)
                        
                    except Exception as e:
                        logger.error(f"Ошибка при кике пользователя {result.user_id}: {e}")
                        continue
                        
            except Exception as e:
                logger.error(f"Ошибка при обработке пользователя {result.user_id}: {e}")
                continue

        if kicked_count > 0:
            await bot.send_message(
                chat_id=chat_id,
                text=f"🔨 Автоматически кикнуто {kicked_count} неактивных пользователей (неактивность более 30 дней)"
            )
            logger.info(f"Автоматический кик завершен. Кикнуто пользователей: {kicked_count}")

    except Exception as e:
        logger.error(f"Ошибка при проверке неактивных пользователей: {e}")

async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """
    Проверяет, является ли пользователь администратором чата.
    Использует кэширование для оптимизации.
    
    Args:
        bot (Bot): Экземпляр бота
        chat_id (int): ID чата
        user_id (int): ID пользователя
        
    Returns:
        bool: True если пользователь админ, False если нет
    """
    cache_key = (chat_id, user_id)
    current_time = datetime.now().timestamp()
    
    # Проверяем кэш
    if cache_key in ADMIN_CACHE:
        cached_result, timestamp = ADMIN_CACHE[cache_key]
        if current_time - timestamp < ADMIN_CACHE_TIMEOUT:
            return cached_result
    
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        is_admin_result = member.status in ("administrator", "creator")
        
        # Сохраняем в кэш
        ADMIN_CACHE[cache_key] = (is_admin_result, current_time)
        return is_admin_result
    except Exception as e:
        logger.error(f"Ошибка при проверке прав администратора для user_id {user_id} в чате {chat_id}: {e}")
        return False

async def award_exp_and_check_level_up(user_id: int, level_exp_amount: int, bonus_exp_amount: int, username: str, message=None, bot=None) -> None:
    """
    Начисляет опыт пользователю, проверяет повышение уровня и отправляет уведомления.
    
    Args:
        user_id (int): ID пользователя
        level_exp_amount (int): Количество level опыта для начисления
        bonus_exp_amount (int): Количество bonus опыта для начисления
        username (str): Имя пользователя
        message: Объект сообщения для ответа (может быть None)
        bot: Экземпляр бота (может быть None)
    """
    try:
        logger.info(f"DEBUG: Начинаем начисление опыта для user_id {user_id}")
        logger.info(f"DEBUG: level_exp_amount = {level_exp_amount}, bonus_exp_amount = {bonus_exp_amount}")
        
        # Получаем текущие данные пользователя
        user = User_listModel.get_or_none(User_listModel.user_id == user_id)
        if not user:
            logger.info(f"DEBUG: Пользователь {user_id} не найден, создаем нового")
            # Создаем пользователя если его нет
            User_listModel.insert({
                User_listModel.created_at: fn.now(),
                User_listModel.user_id: user_id,
                User_listModel.level_exp: 0,
                User_listModel.bonus_exp: 0,
                User_listModel.last_visit: fn.now(),
                User_listModel.rank: 1
            }).execute()
            user = User_listModel.get(User_listModel.user_id == user_id)
        
        # Получаем текущий уровень до начисления опыта
        current_level_exp = user.level_exp
        current_bonus_exp = user.bonus_exp
        current_total_exp = current_level_exp + current_bonus_exp
        current_level = calculate_level(current_total_exp)
        current_rank = user.rank
        
        logger.info(f"DEBUG: Текущие данные пользователя {user_id}:")
        logger.info(f"DEBUG: level_exp = {current_level_exp}, bonus_exp = {current_bonus_exp}")
        logger.info(f"DEBUG: total_exp = {current_total_exp}, current_level = {current_level}, rank = {current_rank}")
        
        # Рассчитываем новый уровень после начисления опыта
        total_exp_to_award = level_exp_amount + bonus_exp_amount
        new_total_exp = current_total_exp + total_exp_to_award
        new_level = calculate_level(new_total_exp)
        
        # Корректируем уровень, если опыта больше, чем нужно для следующего уровня (как в команде /stat)
        exp_for_current = calculate_exp_for_level(new_level)
        exp_for_next = calculate_exp_for_level(new_level + 1)
        while new_total_exp >= exp_for_next and new_level < 20:
            new_level += 1
            exp_for_current = calculate_exp_for_level(new_level)
            exp_for_next = calculate_exp_for_level(new_level + 1)
        
        logger.info(f"DEBUG: После начисления опыта:")
        logger.info(f"DEBUG: total_exp_to_award = {total_exp_to_award}")
        logger.info(f"DEBUG: new_total_exp = {new_total_exp}, new_level = {new_level}")
        logger.info(f"DEBUG: Сравнение: current_rank = {current_rank}, new_level = {new_level}")
        
        # Если уровень повысится и есть объект сообщения
        if new_level > current_rank and message is not None:
            logger.info(f"DEBUG: Уровень повысился! Отправляем уведомление")
            new_rank = get_user_rank(new_level)
            level_up_message = (
                f"🎉 <b>Поздравляем, {username}!</b>\n\n"
                f"🎯 Вы достигли <b>{new_level}-го уровня</b>!\n"
                f"🏆 Новое звание: <b>{new_rank}</b>\n"
                f"⭐ Опыт: <b>{new_total_exp}</b>\n\n"
                f"Продолжайте быть активными! 🚀"
            )
            await message.reply(level_up_message, parse_mode="HTML")
            logger.info(f"DEBUG: Уведомление о повышении уровня отправлено")
        elif new_level > current_rank:
            logger.info(f"DEBUG: Уровень повысился, но нет объекта сообщения для уведомления")
        else:
            logger.info(f"DEBUG: Уровень не повысился")
        
        # Начисляем опыт и обновляем уровень
        logger.info(f"DEBUG: Обновляем данные в БД: level_exp += {level_exp_amount}, bonus_exp += {bonus_exp_amount}, rank = {new_level}")
        User_listModel.update({
            User_listModel.level_exp: User_listModel.level_exp + level_exp_amount,
            User_listModel.bonus_exp: User_listModel.bonus_exp + bonus_exp_amount,
            User_listModel.rank: new_level
        }).where(User_listModel.user_id == user_id).execute()
        
        logger.info(f"DEBUG: Данные пользователя {user_id} успешно обновлены")
            
    except Exception as e:
        logger.error(f"Ошибка при начислении опыта для user_id {user_id}: {e}")
        logger.error(f"DEBUG: Детали ошибки: {str(e)}")










