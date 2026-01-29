"""Репозиторий для работы с транзакциями."""
from typing import Optional, Tuple
from sqlalchemy import select

from shared.models import Transaction, TransactionSource
from .base import BaseRepository
from .user import UserRepository
from ..validators import validate_enum_value


class TransactionRepository(BaseRepository[Transaction]):
    model = Transaction

    async def process_transaction(
        self,
        user_id: int,
        amount: int,
        source: str,
        chat_id: Optional[int] = None,
        description: Optional[str] = None
    ) -> Tuple[Transaction, int]:
        source_enum = validate_enum_value(source, TransactionSource, "source")

        user_repo = UserRepository(self.session)
        new_balance = await user_repo.update_balance_atomic(user_id, amount)

        transaction = Transaction(
            user_id=user_id,
            chat_id=chat_id,
            amount=amount,
            source=source_enum,
            description=description
        )
        self.session.add(transaction)
        await self.session.commit()
        await self.session.refresh(transaction)

        return transaction, new_balance

    async def get_user_transactions(self, user_id: int, limit: int = 50) -> list[Transaction]:
        result = await self.session.execute(
            select(Transaction)
            .where(Transaction.user_id == user_id)
            .order_by(Transaction.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
