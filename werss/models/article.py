# Authored by SONGJUNSONG (School of Finance and Economics, Jilin Business and Technology College)
from sqlalchemy import BigInteger, Index, ForeignKey
from sqlalchemy.orm import relationship
from .base import Base, Column, String, Integer, DateTime, Text, DATA_STATUS


class ArticleBase(Base):
    from_attributes = True
    __tablename__ = 'articles'
    __table_args__ = (
        # 复合索引：按公众号 + 发布时间查询（爬虫去重 / 列表分页常用）
        Index('ix_articles_mp_id_publish_time', 'mp_id', 'publish_time'),
        # 复合索引：按状态 + 发布时间查询（search_articles 默认 status==1 + order by publish_time）
        Index('ix_articles_status_publish_time', 'status', 'publish_time'),
    )
    id = Column(String(255), primary_key=True)
    mp_id = Column(String(255), ForeignKey('feeds.id'), index=True)
    # ORM 关系：article.feed 可直接访问公众号对象，无需应用层手动 join
    feed = relationship("Feed", lazy="joined")
    title = Column(String(1000))
    pic_url = Column(String(500))
    url = Column(String(500))
    description = Column(Text)
    extinfo = Column(Text)
    status = Column(Integer, default=1, index=True)
    publish_time = Column(Integer, index=True)
    create_time = Column(Integer)
    publish_type = Column(Integer)
    publish_src = Column(Integer)
    publish_status = Column(Text)
    original_check_type = Column(Integer)
    in_profile = Column(Integer)
    pre_publish_status = Column(Integer)
    service_type = Column(Integer)
    item_show_types = Column(Integer)
    copyright_stat = Column(Integer)
    has_red_packet_cover = Column(Integer)
    created_at = Column(DateTime, index=True)
    updated_at = Column(BigInteger)
    updated_at_millis = Column(BigInteger)
    is_export = Column(Integer)
    is_read = Column(Integer, default=0)
    is_favorite = Column(Integer, default=0)


class Article(ArticleBase):
    content = Column(Text)
    content_html = Column(Text)

    def to_dict(self):
        return {
            'id': self.id,
            'mp_id': self.mp_id,
            'title': self.title,
            'pic_url': self.pic_url,
            'url': self.url,
            'description': self.description,
            'extinfo': self.extinfo,
            'status': self.status,
            'publish_time': self.publish_time,
            'create_time': self.create_time,
            'publish_type': self.publish_type,
            'publish_src': self.publish_src,
            'publish_status': self.publish_status,
            'original_check_type': self.original_check_type,
            'in_profile': self.in_profile,
            'pre_publish_status': self.pre_publish_status,
            'service_type': self.service_type,
            'item_show_types': self.item_show_types,
            'copyright_stat': self.copyright_stat,
            'has_red_packet_cover': self.has_red_packet_cover,
            'content': self.content,
            'content_html': self.content_html,
            'created_at': self.created_at.isoformat() if self.created_at and hasattr(self.created_at, "isoformat") else self.created_at,
            'updated_at': self.updated_at.isoformat() if self.updated_at and hasattr(self.updated_at, "isoformat") else self.updated_at,
            'updated_at_millis': self.updated_at_millis,
            'is_export': self.is_export,
            'is_read': self.is_read,
            'is_favorite': self.is_favorite
        }
