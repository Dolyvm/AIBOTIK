from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class User(Base):
    """User table for tracking Telegram users"""
    __tablename__ = "users"

    telegram_id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=True)
    avatar_url = Column(String(500), nullable=True)
    balance = Column(Integer, default=1000)
    nsfw_blur = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class Chat(Base):
    """Active chat with a character or world"""
    __tablename__ = "chats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.telegram_id"), nullable=False)
    chat_type = Column(String(20), nullable=False)
    target_id = Column(String(100), nullable=False)
    scenario_index = Column(Integer, default=0)
    msg_count = Column(Integer, default=0)
    history = Column(Text, default="[]")
    state = Column(Text, default='{"affinity": 0, "arousal": 0, "mood": "neutral"}')  # + поля окружение, действие
    summary = Column(Text, default="")
    msgs_since_summary = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
