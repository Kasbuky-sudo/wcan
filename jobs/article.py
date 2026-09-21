from werss.db import DB
from werss.config import cfg


def add_article_to_db(article_data: dict):
    return DB.add_article(article_data, check_exist=True)


def update_mps_sync(mp_id: str):
    from werss.models.feed import Feed
    from datetime import datetime, timezone, timedelta
    import time

    BJT = timezone(timedelta(hours=8))

    session = DB.get_session()
    try:
        feed = session.query(Feed).filter(Feed.id == mp_id).first()
        if feed:
            current_time = int(time.time())
            feed.sync_time = current_time
            feed.updated_at = datetime.now(BJT)
            session.commit()
    finally:
        session.close()
