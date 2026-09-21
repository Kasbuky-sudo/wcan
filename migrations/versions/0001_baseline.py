"""baseline: 基于现有 ORM 模型创建初始表结构

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-24 10:00:00

注意：
- 对于全新部署，执行 `alembic upgrade head` 创建所有表。
- 对于已有数据库（已通过 Base.metadata.create_all 创建过表），
  执行 `alembic stamp head` 标记当前版本，不实际执行 DDL。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0001_baseline'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # articles 表
    op.create_table(
        'articles',
        sa.Column('id', sa.String(255), primary_key=True),
        sa.Column('mp_id', sa.String(255), nullable=True),
        sa.Column('title', sa.String(1000), nullable=True),
        sa.Column('pic_url', sa.String(500), nullable=True),
        sa.Column('url', sa.String(500), nullable=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('extinfo', sa.Text, nullable=True),
        sa.Column('status', sa.Integer, nullable=True),
        sa.Column('publish_time', sa.Integer, nullable=True),
        sa.Column('create_time', sa.Integer, nullable=True),
        sa.Column('publish_type', sa.Integer, nullable=True),
        sa.Column('publish_src', sa.Integer, nullable=True),
        sa.Column('publish_status', sa.Text, nullable=True),
        sa.Column('original_check_type', sa.Integer, nullable=True),
        sa.Column('in_profile', sa.Integer, nullable=True),
        sa.Column('pre_publish_status', sa.Integer, nullable=True),
        sa.Column('service_type', sa.Integer, nullable=True),
        sa.Column('item_show_types', sa.Integer, nullable=True),
        sa.Column('copyright_stat', sa.Integer, nullable=True),
        sa.Column('has_red_packet_cover', sa.Integer, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=True),
        sa.Column('updated_at', sa.BigInteger, nullable=True),
        sa.Column('updated_at_millis', sa.BigInteger, nullable=True),
        sa.Column('is_export', sa.Integer, nullable=True),
        sa.Column('is_read', sa.Integer, nullable=True),
        sa.Column('is_favorite', sa.Integer, nullable=True),
        sa.Column('content', sa.Text, nullable=True),
        sa.Column('content_html', sa.Text, nullable=True),
    )
    # 单列索引
    op.create_index('ix_articles_mp_id', 'articles', ['mp_id'])
    op.create_index('ix_articles_status', 'articles', ['status'])
    op.create_index('ix_articles_publish_time', 'articles', ['publish_time'])
    op.create_index('ix_articles_create_time', 'articles', ['create_time'])
    op.create_index('ix_articles_created_at', 'articles', ['created_at'])
    op.create_index('ix_articles_updated_at_millis', 'articles', ['updated_at_millis'])
    # 复合索引
    op.create_index('ix_articles_mp_id_publish_time', 'articles', ['mp_id', 'publish_time'])
    op.create_index('ix_articles_status_publish_time', 'articles', ['status', 'publish_time'])

    # feeds 表
    op.create_table(
        'feeds',
        sa.Column('id', sa.String(255), primary_key=True),
        sa.Column('mp_name', sa.String(255), nullable=True),
        sa.Column('mp_cover', sa.String(255), nullable=True),
        sa.Column('mp_intro', sa.String(255), nullable=True),
        sa.Column('status', sa.Integer, nullable=True),
        sa.Column('sync_time', sa.Integer, nullable=True),
        sa.Column('update_time', sa.Integer, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=True),
        sa.Column('updated_at', sa.DateTime, nullable=True),
        sa.Column('faker_id', sa.String(255), nullable=True),
    )
    op.create_index('ix_feeds_status', 'feeds', ['status'])

    # users 表
    op.create_table(
        'users',
        sa.Column('id', sa.String(255), primary_key=True),
        sa.Column('username', sa.String(50), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('is_active', sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('users')
    op.drop_table('feeds')
    op.drop_table('articles')
