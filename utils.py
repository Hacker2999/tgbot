from datetime import datetime, timezone
from typing import Optional

from model import AnekModel


def quota_check(userid: int, qcount: int) -> bool:
    """
    Проверяет, превысил ли пользователь дневной лимит анекдотов.
    Если лимит превышен и прошёл день с последнего запроса, сбрасывает счётчик.
    Возвращает True, если пользователь может получить анекдот, иначе False.
    """
    q = (
        AnekModel.select(AnekModel.created_at)
        .where(AnekModel.user_id == userid)
        .first()
    )
    if not q or not hasattr(q, 'created_at'):
        # Пользователь не найден в БД, разрешить действие (будет добавлен при первом использовании)
        return True
    recent_time = q.created_at
    now = datetime.now(timezone.utc)
    # Убедиться, что recent_time имеет информацию о часовом поясе
    if recent_time.tzinfo is None:
        recent_time = recent_time.replace(tzinfo=timezone.utc)
    days_passed = (now - recent_time).days
    if days_passed >= 1:
        q2 = (
            AnekModel
            .update({AnekModel.count: 0})
            .where(AnekModel.user_id == userid)
        )
        q2.execute()
        return True
    elif qcount < 3:
        return True
    else:
        return False


def calculate_level(exp: int) -> int:
    """
    Рассчитывает уровень пользователя на основе опыта.
    Формула основана на таблице уровней:
    Уровень 1: 0-149 опыта
    Уровень 2: 150-249 опыта
    Уровень 3: 250-349 опыта
    И так далее...
    """
    if exp < 150:
        return 1
    return 1 + (exp - 150) // 100


def calculate_exp_for_level(level: int) -> int:
    """
    Рассчитывает требуемый опыт для достижения указанного уровня.
    Формула: опыт = 150 + (уровень - 1) * 100
    """
    return 150 + (level - 1) * 100


def calculate_messages_for_level(level: int) -> int:
    """
    Рассчитывает требуемое количество сообщений для достижения указанного уровня.
    Формула основана на таблице:
    Уровень 1: 150 сообщений
    Уровень 2: 400 сообщений
    Уровень 3: 750 сообщений
    И так далее...
    """
    if level == 1:
        return 150
    return 150 + (level - 1) * 250 + (level - 1) * (level - 2) * 50


def get_user_rank(level: int) -> str:
    """
    Возвращает звание пользователя на основе его уровня.
    Если уровень больше 20, возвращает звание для 20 уровня.
    """
    try:
        with open("ranks.txt", "r", encoding="utf-8") as file:
            ranks = [line.strip() for line in file if line.strip()]
        
        if not ranks:
            return "Неизвестное звание"
            
        # Убираем номер уровня из строки (например, "1. " -> "")
        ranks = [rank.split(". ", 1)[1] if ". " in rank else rank for rank in ranks]
        
        # Если уровень больше 20, возвращаем последнее звание
        if level > 20:
            return ranks[-1]
            
        # Возвращаем звание для текущего уровня (уровни начинаются с 1, а индексы с 0)
        return ranks[level - 1]
    except Exception as e:
        logger.error(f"Ошибка при получении звания: {e}")
        return "Неизвестное звание"









