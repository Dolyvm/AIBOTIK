from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean,
    ForeignKey, Enum as SQLEnum, ARRAY, BigInteger
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import enum

Base = declarative_base()

async def get_async_session():
    from shared.database import get_db
    async for session in get_db():
        yield session


class MessageRole(enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class TransactionSource(enum.Enum):
    DAILY_BONUS = "daily_bonus"
    PURCHASE = "purchase"
    MESSAGE_SENT = "message_sent"
    IMAGE_GENERATED = "image_generated"
    ADMIN_GRANT = "admin_grant"


class User(Base):
    """User table for tracking Telegram users"""
    __tablename__ = "users"

    telegram_id = Column(BigInteger, primary_key=True)
    username = Column(String(255), nullable=True)
    avatar_url = Column(String(500), nullable=True)
    balance = Column(Integer, default=1000)

    is_subscribed = Column(Boolean, default=False)
    subscription_end_date = Column(DateTime, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    last_active_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    settings = relationship("UserSettings", back_populates="user", uselist=False, cascade="all, delete-orphan")
    chats = relationship("Chat", back_populates="user", cascade="all, delete-orphan")
    images = relationship("GeneratedImage", back_populates="user", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")


class UserSettings(Base):
    """User settings (one-to-one with User)"""
    __tablename__ = "user_settings"

    user_id = Column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), primary_key=True)
    nsfw_blur = Column(Boolean, default=True)
    language = Column(String(10), default="ru")
    nickname = Column(String(50), nullable=True, default=None)

    user = relationship("User", back_populates="settings")


class Character(Base):
    """Character content table (replaces JSON files)"""
    __tablename__ = "characters"

    id = Column(String(100), primary_key=True) 
    name = Column(String(255), nullable=False)
    is_public = Column(Boolean, nullable=False, default=False)
    description = Column(Text, nullable=False)
    short_description = Column(String(30), nullable=True, default="")
    personality = Column(Text, nullable=False)

    visual_data = Column(JSONB, nullable=False)
    scenarios = Column(JSONB, default=[])

    tags = Column(ARRAY(String), default=[])
    is_nsfw = Column(Boolean, default=False)
    created_by_username_id = Column(BigInteger, ForeignKey("users.telegram_id", ondelete="SET NULL"), nullable=True)
    created_by_username = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class World(Base):
    """World content table (replaces JSON files)"""
    __tablename__ = "worlds"

    id = Column(String(100), primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    short_description = Column(String(30), nullable=True, default="")
    cover_image = Column(String(500), nullable=True)

    scenarios = Column(JSONB, default=[])
    locations = Column(JSONB, default=[])

    tags = Column(ARRAY(String), default=[])
    is_nsfw = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Chat(Base):
    """Active chat session with a character or world"""
    __tablename__ = "chats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False)

    chat_type = Column(String(20), nullable=False)
    target_id = Column(String(100), nullable=False)
    scenario_index = Column(Integer, default=0)

    affinity = Column(Integer, default=0)
    arousal = Column(Integer, default=0)
    current_location = Column(String(255), nullable=True)
    current_mood = Column(String(100), default="neutral")

    state_meta = Column(JSONB, default={})

    summary = Column(Text, default="")
    msgs_since_summary = Column(Integer, default=0)

    last_auto_photo_at = Column(Integer, default=0)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="chats")
    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan")
    images = relationship("GeneratedImage", back_populates="chat", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="chat")


class Message(Base):
    """Individual message in a chat"""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True)

    role = Column(SQLEnum(MessageRole), nullable=False)
    content = Column(Text, nullable=False)
    tokens_used = Column(Integer, default=0)

    is_auto_generated = Column(Boolean, default=False, nullable=False)
    
    created_at = Column(DateTime, server_default=func.now(), index=True)

    chat = relationship("Chat", back_populates="messages")


class GeneratedImage(Base):
    """Generated images gallery"""
    __tablename__ = "generated_images"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False)
    chat_id = Column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), nullable=True)

    provider_url = Column(String(1000), nullable=True)

    local_path = Column(String(500), nullable=True)

    prompt = Column(Text, nullable=False)

    file_size = Column(Integer, nullable=True)  
    content_type = Column(String(50), nullable=True)  
    nsfw_level = Column(Integer, default=0, nullable=True)  

    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="images")
    chat = relationship("Chat", back_populates="images")

    @property
    def public_url(self) -> str:
        if self.local_path:
            from shared.config import IMAGES_BASE_URL
            return f"{IMAGES_BASE_URL}/{self.local_path}"
        return self.provider_url  


class Transaction(Base):
    """Balance transaction log"""
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False)
    chat_id = Column(Integer, ForeignKey("chats.id", ondelete="SET NULL"), nullable=True)

    amount = Column(Integer, nullable=False) 
    source = Column(SQLEnum(TransactionSource), nullable=False)
    description = Column(String(500), nullable=True)

    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="transactions")
    chat = relationship("Chat", back_populates="transactions")


class Prompt(Base):
    """Prompt templates for AI interactions"""
    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    category = Column(String(50), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
