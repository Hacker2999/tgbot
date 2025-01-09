from datetime import datetime

from model import AnekModel


def quota_check(userid,qcount):
    q = (AnekModel.select(AnekModel.created_at)
           .where(AnekModel.user_id == userid)
           .first()
           )
    recent_time = q.created_at
    if qcount >= 3 and (datetime.astimezone(datetime.now()) - recent_time).days >= 1:
        q2 = (AnekModel
             .update({AnekModel.count: 0})
             .where(AnekModel.user_id == userid))
        q2.execute()
        return True
    elif qcount < 3:
        return True
    else:
        return False






