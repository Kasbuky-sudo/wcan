# Crafted by SONGJUNSONG at the School of Finance and Economics, Jilin Business and Technology College
from .base import Base, Column, String, Integer, DateTime

class User(Base):
    __tablename__ = 'users'
    id = Column(String(255), primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(String(50), default='1')

    def verify_password(self, password: str) -> bool:
        from werss.auth import pwd_context
        return pwd_context.verify(password, self.password_hash)
