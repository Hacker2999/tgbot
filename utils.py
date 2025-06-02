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
    if qcount >= 3 and days_passed >= 1:
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






