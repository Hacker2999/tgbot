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

from handlers import is_admin
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
        return 1
    if exp >= MAX_EXP:
        return MAX_LEVEL
        
    try:
        a = DIFF_INCREASE / 2
        b = BASE_DIFF - DIFF_INCREASE
        c = -(exp + BASE_DIFF - BASE_EXP)
        
        discriminant = b**2 - 4*a*c
        level = int((-b + (discriminant)**0.5) / (2*a))
        
        return min(max(level, 1), MAX_LEVEL)
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
        return int(BASE_EXP + BASE_DIFF*(level-1) + (DIFF_INCREASE/2)*(level-1)*(level-2))
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
                User_listModel.visit_streak: 1
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
                user = User_listModel.get_or_none(User_listModel.user_id == result.user_id)
                if not user:
                    # Создаём пользователя, если его нет
                    User_listModel.insert({
                        User_listModel.created_at: fn.now(),
                        User_listModel.user_id: result.user_id,
                        User_listModel.bonus_exp: 0,
                        User_listModel.last_visit: fn.now(),
                    }).execute()
                # Теперь начисляем награду
                User_listModel.update({User_listModel.bonus_exp: User_listModel.bonus_exp + rewards[idx]}).where(User_listModel.user_id == result.user_id).execute()
                try:
                    member = await bot.get_chat_member(chat_id, result.user_id)
                    username = member.user.username if member.user.username is not None else member.user.first_name
                    place = idx + 1
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










