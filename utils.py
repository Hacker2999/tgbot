from datetime import datetime, timezone
from typing import Optional

from model import AnekModel


def quota_check(userid: int, qcount: int) -> bool:
    """
    Checks if the user has exceeded their daily quota for anecdotes.
    If the quota is exceeded and a day has passed since the last request, resets the count.
    Returns True if the user can receive an anecdote, False otherwise.
    """
    q = (
        AnekModel.select(AnekModel.created_at)
        .where(AnekModel.user_id == userid)
        .first()
    )
    if not q or not hasattr(q, 'created_at'):
        # User not found in DB, allow action (will be inserted on first use)
        return True
    recent_time = q.created_at
    now = datetime.now(timezone.utc)
    # Ensure recent_time is timezone-aware
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






