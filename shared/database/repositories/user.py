from typing import Optional
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from shared.models import User, UserSettings
from .base import BaseRepository
from ..exceptions import EntityNotFoundError, InsufficientBalanceError
from shared.services.cache import get_cache

class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        result = await self.session.execute(
            select(User)
            .options(selectinload(User.settings))
            .where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, telegram_id: int, username: Optional[str] = None) -> User:
        user = await self.get_by_telegram_id(telegram_id)

        if not user:
            user = User(
                telegram_id=telegram_id,
                username=username,
                balance=1000
            )
            self.session.add(user)

            settings = UserSettings(user_id=telegram_id)
            self.session.add(settings)

            await self.session.commit()

            result = await self.session.execute(
                select(User)
                .options(selectinload(User.settings))
                .where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one()

        return user

    async def get_balance(self, telegram_id: int) -> int:
        result = await self.session.execute(
            select(User.balance).where(User.telegram_id == telegram_id)
        )
        balance = result.scalar_one_or_none()
        if balance is None:
            raise EntityNotFoundError("User", telegram_id)
        return balance

    async def update_balance_atomic(self, telegram_id: int, amount: int) -> int:
        if amount < 0:
                                            
            result = await self.session.execute(
                update(User)
                .where(
                    User.telegram_id == telegram_id,
                    User.balance >= abs(amount)
                )
                .values(balance=User.balance + amount)
                .returning(User.balance)
            )
            new_balance = result.scalar_one_or_none()

            if new_balance is None:
                current = await self.get_balance(telegram_id)
                raise InsufficientBalanceError(current, abs(amount))
        else:
                        
            result = await self.session.execute(
                update(User)
                .where(User.telegram_id == telegram_id)
                .values(balance=User.balance + amount)
                .returning(User.balance)
            )
            new_balance = result.scalar_one_or_none()
            if new_balance is None:
                raise EntityNotFoundError("User", telegram_id)

        await self.session.commit()

        cache = get_cache()
        if cache:
            await cache.invalidate_user(telegram_id)

        return new_balance

    async def update_settings(self, telegram_id: int, nsfw_blur: Optional[bool] = None, nickname: Optional[str] = None) -> bool:
        updates = {}
        if nsfw_blur is not None:
            updates["nsfw_blur"] = nsfw_blur
        if nickname is not None:
            updates["nickname"] = nickname.strip()[:50] if nickname.strip() else None

        if not updates:
            return True

        await self.session.execute(
            update(UserSettings)
            .where(UserSettings.user_id == telegram_id)
            .values(**updates)
        )
        await self.session.commit()

        cache = get_cache()
        if cache:
            await cache.invalidate_user(telegram_id)

        return True
