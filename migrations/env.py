"""Alembic 迁移环境配置。

从 config.yaml 读取数据库连接字符串，导入所有 ORM 模型以支持 autogenerate。
"""
from __future__ import with_statement

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# 将项目根目录加入 sys.path，使能导入项目模块
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Alembic 配置对象
config = context.config

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ====================== 动态读取数据库连接字符串 ======================
# 优先级：环境变量 WCAN_DB > config.yaml 的 db 字段 > alembic.ini 默认值
db_url = os.environ.get('WCAN_DB', '')
if not db_url:
    try:
        from werss.config import cfg
        db_url = cfg.get('db', 'sqlite:///data/articles.db')
    except Exception:
        pass  # 兜底使用 alembic.ini 中的 sqlalchemy.url

if db_url:
    config.set_main_option('sqlalchemy.url', db_url)

# ====================== 导入所有 ORM 模型 ======================
# 必须导入所有模型模块，否则 autogenerate 无法检测到表结构变更
from werss.models.base import Base  # noqa: E402
import werss.models.article  # noqa: E402,F401
import werss.models.feed  # noqa: E402,F401
import werss.models.user  # noqa: E402,F401

target_metadata = Base.metadata


def run_migrations_offline():
    """离线模式：生成 SQL 脚本而不连接数据库。

    使用场景：CI/CD 中生成迁移 SQL 供 DBA 审核。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # 比较类型和服务器默认值，便于检测列类型变更
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """在线模式：直接连接数据库执行迁移。

    使用场景：开发/部署时直接升级数据库。
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
