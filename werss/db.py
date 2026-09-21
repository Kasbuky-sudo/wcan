# Maintained by SONGJUNSONG — Jilin Business and Technology College, School of Finance and Economics
from sqlalchemy import create_engine, Engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, scoped_session
from contextlib import contextmanager
from werss.models.base import Base
from werss.config import cfg
from werss.print import print_success, print_warning, print_error, print_info


class Db:
    def __init__(self, tag="默认"):
        self.Session = None
        self.engine = None
        self.tag = tag
        self.session_factory = None
        print_success(f"[{tag}]连接初始化")

    def get_engine(self) -> Engine:
        if self.engine is None:
            raise ValueError("Database connection has not been initialized.")
        return self.engine

    def get_session_factory(self):
        return sessionmaker(bind=self.engine, autoflush=True, expire_on_commit=True, future=True)

    def init(self, con_str: str) -> None:
        try:
            if con_str.startswith('sqlite:///'):
                import os
                db_path = con_str[10:]
                if not os.path.exists(db_path):
                    os.makedirs(os.path.dirname(db_path), exist_ok=True)
                    open(db_path, 'w').close()

            connect_args = {}
            engine_kwargs = {
                "echo": False,
            }
            if con_str.startswith('sqlite:///'):
                # SQLite 专用配置
                connect_args = {"check_same_thread": False}
                # 加 busy_timeout 避免多线程写时 "database is locked"
                # 用 StaticPool 让多线程共享同一连接（SQLite 文件级锁，多连接反而争用）
                from sqlalchemy.pool import StaticPool
                engine_kwargs["poolclass"] = StaticPool
                engine_kwargs["connect_args"] = {
                    "check_same_thread": False,
                    "timeout": 30,  # busy_timeout 30s
                }
            else:
                # MySQL/PostgreSQL 配置（预留，当前未使用）
                engine_kwargs["pool_size"] = 5
                engine_kwargs["max_overflow"] = 10
                engine_kwargs["pool_timeout"] = 30
                engine_kwargs["pool_recycle"] = 3600
                engine_kwargs["connect_args"] = connect_args

            self.engine = create_engine(con_str, **engine_kwargs)

            if con_str.startswith('sqlite:///'):
                @event.listens_for(self.engine, "connect")
                def _set_sqlite_pragma(dbapi_conn, connection_record):
                    # 开启 WAL 模式：读写不互斥，并发性能更好
                    cursor = dbapi_conn.cursor()
                    cursor.execute("PRAGMA journal_mode=WAL")
                    cursor.execute("PRAGMA busy_timeout=30000")
                    cursor.close()

            self.session_factory = self.get_session_factory()
        except Exception as e:
            print_error(f"Error creating database connection: {e}")
            raise

    def get_session(self):
        if self.session_factory is None:
            self.init(cfg.get("db", "sqlite:///data/articles.db"))
        return self.session_factory()

    @contextmanager
    def session_scope(self):
        """Session 上下文管理器，自动 close（异常时也保证 close，防止连接泄漏）"""
        session = self.get_session()
        try:
            yield session
        finally:
            session.close()

    def create_tables(self):
        try:
            Base.metadata.create_all(self.engine)
            print_info("数据库表创建/同步完成")
        except Exception as e:
            print_error(f"Error creating tables: {e}")

    def add_article(self, article_data: dict, check_exist: bool = True) -> bool:
        from werss.models.article import Article
        from datetime import datetime, timezone, timedelta
        BJT = timezone(timedelta(hours=8))
        session = self.get_session()
        try:
            if check_exist:
                existing = session.query(Article).filter(Article.id == article_data.get("id")).first()
                if existing:
                    return False
            now = datetime.now(BJT)
            article = Article(
                id=article_data.get("id"),
                mp_id=article_data.get("mp_id"),
                title=article_data.get("title"),
                pic_url=article_data.get("pic_url"),
                url=article_data.get("url"),
                description=article_data.get("description", ""),
                content=article_data.get("content", ""),
                content_html=article_data.get("content_html", ""),
                publish_time=article_data.get("publish_time"),
                create_time=int(now.timestamp()),
                created_at=now,
                updated_at=int(now.timestamp()),
                updated_at_millis=int(now.timestamp() * 1000),
                status=1,
                is_export=0,
                is_read=0,
                is_favorite=0
            )
            session.add(article)
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            print_error(f"添加文章失败: {e}")
            return False
        finally:
            session.close()

    def get_all_mps(self):
        from werss.models.feed import Feed
        session = self.get_session()
        try:
            return session.query(Feed).filter(Feed.status == 1).all()
        finally:
            session.close()


DB = Db("主库")
