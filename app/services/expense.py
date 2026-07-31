from datetime import datetime
from decimal import Decimal
from typing import Any

from app.database.enums import PaymentMethod
from app.database.models.transaction import Transaction
from app.database.repositories.transaction import TransactionRepository
from app.utils.timezone import (
    get_month_window,
    get_range_window,
    get_today_window,
    get_week_window,
    parse_date,
    sgt_to_utc,
)


class ExpenseService:
    def __init__(self):
        self.transaction_repo = TransactionRepository()

    async def add_transaction(
        self,
        user_id: int,
        amount: float | Decimal,
        merchant: str,
        payment_method: PaymentMethod,
        transaction_time: datetime,
        description: str | None = None,
    ) -> Transaction:
        """Add a new transaction for a user."""
        if not merchant:
            raise ValueError("Merchant is required")

        amount_decimal = Decimal(str(amount))
        transaction_time_utc = sgt_to_utc(transaction_time)
        return await self.transaction_repo.insert(
            user_id=user_id,
            amount=float(amount_decimal),
            merchant=merchant,
            payment_method=payment_method,
            transaction_time=transaction_time_utc,
            description=description,
        )

    async def delete_transaction(self, transaction_id: int, user_id: int) -> bool:
        """Delete a transaction (soft delete) if owned by user."""
        transaction = await self.transaction_repo.get_by_id_for_user(transaction_id, user_id)
        if not transaction:
            return False

        await self.transaction_repo.soft_delete(transaction)
        return True

    async def edit_transaction(
        self,
        transaction_id: int,
        user_id: int,
        field: str,
        value: Any,
    ) -> Transaction | None:
        """Edit a transaction field if owned by user."""
        allowed_fields = {"amount", "merchant", "description", "transaction_time"}
        if field not in allowed_fields:
            raise ValueError(f"Field must be one of: {allowed_fields}")

        transaction = await self.transaction_repo.get_by_id_for_user(transaction_id, user_id)
        if not transaction:
            return None

        if field == "amount":
            value = float(Decimal(str(value)))
        elif field == "transaction_time":
            if isinstance(value, str):
                value = parse_date(value)
            value = sgt_to_utc(value)

        await self.transaction_repo.update_field(transaction, field, value)
        return transaction

    async def get_latest_transactions(self, user_id: int, count: int = 10) -> list[Transaction]:
        """Get latest transactions for a user."""
        return await self.transaction_repo.list_latest_for_user(user_id, count)

    async def get_today_spending(self, user_id: int) -> float:
        """Get today's total spending (signed, including refunds)."""
        start, end = get_today_window()
        return await self.transaction_repo.sum_amount(user_id, start, end)

    async def get_week_spending(self, user_id: int) -> float:
        """Get this week's total spending (signed, including refunds)."""
        start, end = get_week_window()
        return await self.transaction_repo.sum_amount(user_id, start, end)

    async def get_month_spending(self, user_id: int) -> float:
        """Get this month's total spending (signed, including refunds)."""
        start, end = get_month_window()
        return await self.transaction_repo.sum_amount(user_id, start, end)

    async def search_transactions(self, user_id: int, merchant_substring: str) -> list[Transaction]:
        """Search transactions by merchant name (case-insensitive)."""
        return await self.transaction_repo.search_transactions(user_id, merchant_substring)

    async def get_range_transactions(
        self,
        user_id: int,
        start_date: datetime | str,
        end_date: datetime | str,
    ) -> tuple[list[Transaction], int, bool]:
        """Get transactions in a date range.

        Returns:
            Tuple of (transactions, total_count, is_truncated)
            where is_truncated is True if total_count > 200.
        """
        if isinstance(start_date, str):
            start_date = parse_date(start_date)
        if isinstance(end_date, str):
            end_date = parse_date(end_date)

        start_sgt, end_sgt = get_range_window(start_date, end_date)
        rows, total_count = await self.transaction_repo.list_in_range_for_user(
            user_id, start_sgt, end_sgt
        )
        return rows, total_count, total_count > 200
