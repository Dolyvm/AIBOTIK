from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, update
from typing import Optional
import os
import json

from .models import Base, User, Chat


# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://rpbot:password@localhost:5432/rpbot")
# Convert to async URL
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Initialize database tables"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """Get database session"""
    async with async_session() as session:
        return session


# User operations
async def get_or_create_user(
    telegram_id: int,
    username: Optional[str] = None,
    avatar_url: Optional[str] = None
) -> User:
    """Get existing user or create new one"""
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                telegram_id=telegram_id,
                username=username,
                avatar_url=avatar_url
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

        return user


async def get_user(telegram_id: int) -> Optional[User]:
    """Get user by Telegram ID"""
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


async def update_balance(telegram_id: int, delta: int) -> int:
    """Update user balance and return new balance"""
    async with async_session() as session:
        await session.execute(
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(balance=User.balance + delta)
        )
        await session.commit()

        # Get updated balance
        result = await session.execute(
            select(User.balance).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one()


# Chat operations
async def get_active_chat(user_id: int) -> Optional[Chat]:
    """Get active chat for user"""
    async with async_session() as session:
        result = await session.execute(
            select(Chat)
            .where(Chat.user_id == user_id, Chat.is_active == True)
            .order_by(Chat.updated_at.desc())
        )
        return result.scalar_one_or_none()


async def get_user_chats(user_id: int) -> list[Chat]:
    """Get all user chats"""
    async with async_session() as session:
        result = await session.execute(
            select(Chat)
            .where(Chat.user_id == user_id)
            .order_by(Chat.updated_at.desc())
        )
        return list(result.scalars().all())


async def create_or_reset_chat(
    user_id: int,
    chat_type: str,
    target_id: str,
    scenario_index: int = 0
) -> Chat:
    """Create new chat or reset existing one"""
    async with async_session() as session:
        # Deactivate all other chats
        await session.execute(
            update(Chat)
            .where(Chat.user_id == user_id)
            .values(is_active=False)
        )

        # Check if chat with this character/world exists
        result = await session.execute(
            select(Chat)
            .where(
                Chat.user_id == user_id,
                Chat.chat_type == chat_type,
                Chat.target_id == target_id
            )
        )
        existing_chat = result.scalar_one_or_none()

        if existing_chat:
            existing_chat.scenario_index = scenario_index
            existing_chat.msg_count = 0
            existing_chat.history = "[]"
            existing_chat.state = '{"affinity": 0, "arousal": 0, "mood": "neutral"}'
            existing_chat.summary = ""
            existing_chat.msgs_since_summary = 0
            existing_chat.is_active = True
            await session.commit()
            await session.refresh(existing_chat)
            return existing_chat
        else:
            # Create new chat
            chat = Chat(
                user_id=user_id,
                chat_type=chat_type,
                target_id=target_id,
                scenario_index=scenario_index
            )
            session.add(chat)
            await session.commit()
            await session.refresh(chat)
            return chat


async def update_chat_history(chat_id: int, history: list, msg_count: int):
    """Update chat history and message count"""
    async with async_session() as session:
        await session.execute(
            update(Chat)
            .where(Chat.id == chat_id)
            .values(
                history=json.dumps(history, ensure_ascii=False),
                msg_count=msg_count
            )
        )
        await session.commit()


async def set_active_chat(user_id: int, chat_id: int):
    """Set specific chat as active"""
    async with async_session() as session:
        # Deactivate all chats
        await session.execute(
            update(Chat)
            .where(Chat.user_id == user_id)
            .values(is_active=False)
        )

        # Activate selected chat
        await session.execute(
            update(Chat)
            .where(Chat.id == chat_id)
            .values(is_active=True)
        )
        await session.commit()


async def update_chat_full(
    chat_id: int,
    history: list,
    state: dict,
    summary: str,
    msgs_since_summary: int,
    msg_count: int
):
    """Update chat with full state including history, state, summary"""
    async with async_session() as session:
        await session.execute(
            update(Chat)
            .where(Chat.id == chat_id)
            .values(
                history=json.dumps(history, ensure_ascii=False),
                state=json.dumps(state, ensure_ascii=False),
                summary=summary,
                msgs_since_summary=msgs_since_summary,
                msg_count=msg_count
            )
        )
        await session.commit()
