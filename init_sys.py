from werss.models.base import Base
from werss.db import DB
from werss.config import cfg
from werss.auth import pwd_context
from werss.print import print_info, print_error
import os


def init_user(username: str = "admin", password: str = "admin@123"):
    session = DB.get_session()
    try:
        from werss.models.user import User
        session.add(User(
            id="0",
            username=username,
            password_hash=pwd_context.hash(password),
        ))
        session.commit()
        print_info(f"初始化用户成功, 请使用以下凭据登录：{username}")
    except Exception as e:
        session.rollback()
    finally:
        session.close()


def sync_models():
    try:
        DB.init(cfg.get("db", "sqlite:///data/articles.db"))
        # 显式 import 所有模型，确保它们注册到 Base.metadata
        # 否则 create_all 可能空操作（模型类未被加载 → metadata 里没表）
        import werss.models  # noqa: F401 — 触发 __init__.py 导入 Feed/Article/User
        DB.create_tables()
        print_info("模型同步完成")
    except Exception as e:
        print_error(f"模型同步失败: {e}")


def init():
    sync_models()
    try:
        init_user()
    except Exception:
        pass


if __name__ == '__main__':
    init()
