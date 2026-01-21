from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, selectinload
from sqlalchemy import select, update, delete
from contextlib import asynccontextmanager
from typing import Optional
import os

from .models import Base, User, UserSettings, Chat, Message, Transaction, MessageRole, TransactionSource, GeneratedImage

from config import DATABASE_URL 

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def get_session():
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


# User operations
async def get_or_create_user(
    telegram_id: int,
    username: Optional[str] = None
) -> User:
    async with async_session() as session:
        result = await session.execute(
            select(User)
            .options(selectinload(User.settings))
            .where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                telegram_id=telegram_id,
                username=username,
                balance=1000
            )
            session.add(user)

            settings = UserSettings(
                user_id=telegram_id
            )
            session.add(settings)

            await session.commit()

            await session.refresh(user)
            result = await session.execute(
                select(User)
                .options(selectinload(User.settings))
                .where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one()

        return user


async def get_user(telegram_id: int) -> Optional[User]:
    async with async_session() as session:
        result = await session.execute(
            select(User)
            .options(selectinload(User.settings))
            .where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


async def create_chat(
    user_id: int,
    target_id: str,
    chat_type: str,
    scenario_index: int = 0
) -> Chat:
    async with async_session() as session:
        result = await session.execute(
            select(Chat)
            .where(
                Chat.user_id == user_id,
                Chat.target_id == target_id,
                Chat.chat_type == chat_type
            )
        )
        existing_chat = result.scalar_one_or_none()

        if existing_chat:
            await session.execute(
                update(Chat)
                .where(Chat.user_id == user_id, Chat.id != existing_chat.id)
                .values(is_active=False)
            )

            await session.execute(
                delete(Message).where(Message.chat_id == existing_chat.id)
            )
            await session.execute(
                delete(GeneratedImage).where(GeneratedImage.chat_id == existing_chat.id)
            )

            existing_chat.is_active = True
            existing_chat.scenario_index = scenario_index
            existing_chat.affinity = 0
            existing_chat.arousal = 0
            existing_chat.current_location = None
            existing_chat.current_mood = "neutral"
            existing_chat.summary = ""
            existing_chat.msgs_since_summary = 0
            existing_chat.state_meta = {}

            await session.commit()
            await session.refresh(existing_chat)
            return existing_chat
        else:
            await session.execute(
                update(Chat)
                .where(Chat.user_id == user_id)
                .values(is_active=False)
            )
            chat = Chat(
                user_id=user_id,
                target_id=target_id,
                chat_type=chat_type,
                scenario_index=scenario_index,
                affinity=0,
                arousal=0,
                current_location=None,
                current_mood="neutral",
                summary="",
                state_meta={},
                is_active=True
            )
            session.add(chat)
            await session.commit()
            await session.refresh(chat)

            return chat


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


async def update_chat_metrics(chat_id: int, metrics_dict: dict):
    async with async_session() as session:
        await session.execute(
            update(Chat)
            .where(Chat.id == chat_id)
            .values(**metrics_dict)
        )
        await session.commit()


async def set_active_chat(user_id: int, chat_id: int):
    async with async_session() as session:
        await session.execute(
            update(Chat)
            .where(Chat.user_id == user_id)
            .values(is_active=False)
        )

        await session.execute(
            update(Chat)
            .where(Chat.id == chat_id)
            .values(is_active=True)
        )
        await session.commit()


async def add_message(
    chat_id: int,
    role: str,
    content: str,
    tokens_used: int = 0
) -> Message:
    async with async_session() as session:
        message = Message(
            chat_id=chat_id,
            role=MessageRole[role.upper()],
            content=content,
            tokens_used=tokens_used
        )
        session.add(message)
        await session.execute(
            update(Chat)
            .where(Chat.id == chat_id)
            .values(msgs_since_summary=Chat.msgs_since_summary + 1)
        )

        await session.commit()
        await session.refresh(message)

        return message


async def get_chat_history(chat_id: int, limit: int = 20) -> list[Message]:
    async with async_session() as session:
        result = await session.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = list(result.scalars().all())
        messages.reverse()

        return messages


async def process_transaction(
    user_id: int,
    amount: int,
    source: str,
    chat_id: Optional[int] = None,
    description: Optional[str] = None
) -> tuple[Transaction, int]:
    async with async_session() as session:
        result = await session.execute(
            select(User.balance)
            .where(User.telegram_id == user_id)
        )
        current_balance = result.scalar_one()

        new_balance = current_balance + amount
        if new_balance < 0:
            raise ValueError(
                f"Недостаточно средств. Текущий баланс: {current_balance}, "
                f"требуется списать: {abs(amount)}"
            )

        await session.execute(
            update(User)
            .where(User.telegram_id == user_id)
            .values(balance=new_balance)
        )

        transaction = Transaction(
            user_id=user_id,
            chat_id=chat_id,
            amount=amount,
            source=TransactionSource[source.upper()],
            description=description
        )
        session.add(transaction)

        await session.commit()
        await session.refresh(transaction)

        return transaction, new_balance


async def get_user_balance(user_id: int) -> int:
    async with async_session() as session:
        result = await session.execute(
            select(User.balance)
            .where(User.telegram_id == user_id)
        )
        return result.scalar_one()


async def get_user_transactions(
    user_id: int,
    limit: int = 50
) -> list[Transaction]:
    async with async_session() as session:
        result = await session.execute(
            select(Transaction)
            .where(Transaction.user_id == user_id)
            .order_by(Transaction.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

async def save_generated_image(
    user_id: int,
    chat_id: int,
    prompt: str,
    provider_url: str
):
    async with async_session() as session:
        image = GeneratedImage(
            user_id=user_id,
            chat_id=chat_id,
            prompt=prompt,
            provider_url=provider_url
        )
        session.add(image)
        await session.commit()
        await session.refresh(image)

        return image


async def get_chat_images(chat_id: int) -> list:
    async with async_session() as session:
        result = await session.execute(
            select(GeneratedImage)
            .where(GeneratedImage.chat_id == chat_id)
            .order_by(GeneratedImage.created_at.asc())
        )
        images = list(result.scalars().all())
        return [
            {
                "role": "assistant",
                "avatar": img.provider_url,
                "timestamp": img.created_at.isoformat()
            }
            for img in images
        ]


async def reset_chat_history(chat_id: int):
    from .models import Message, GeneratedImage
    from sqlalchemy import delete

    async with async_session() as session:
        await session.execute(
            delete(Message)
            .where(Message.chat_id == chat_id)
        )
        await session.execute(
            delete(GeneratedImage)
            .where(GeneratedImage.chat_id == chat_id)
        )

        await session.execute(
            update(Chat)
            .where(Chat.id == chat_id)
            .values(
                affinity=0,
                arousal=0,
                current_location=None,
                current_mood="neutral",
                summary="",
                msgs_since_summary=0,
                state_meta={}
            )
        )
        await session.commit()
