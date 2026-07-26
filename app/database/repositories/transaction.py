from datetime import datetime, timezone
from decimal import Decimal

from tortoise.functions import Coalesce, Sum

from app.database.enums import PaymentMethod
from app.database.models.transaction import Transaction


class TransactionRepository:
    async def insert(
        self,
        user_id: int,
        amount: float | Decimal | None,
        merchant: str,
        payment_method: PaymentMethod,
        transaction_time: datetime,
        description: str | None = None,
    ) -> Transaction:
        if amount is None:
            amount = Decimal("0")
        if isinstance(amount, float):
            amount = Decimal(str(amount))
        transaction = await Transaction.create(
            user_id=user_id,
            amount=amount,
            merchant=merchant,
            payment_method=payment_method,
            transaction_time=transaction_time,
            description=description,
        )
        return transaction

    async def get_by_id_for_user(self, transaction_id: int, user_id: int) -> Transaction | None:
        return await Transaction.filter(
            id=transaction_id,
            user_id=user_id,
            deleted_at__isnull=True
        ).first()

    async def list_latest_for_user(self, user_id: int, count: int = 10) -> list[Transaction]:
        return await Transaction.filter(
            user_id=user_id,
            deleted_at__isnull=True
        ).order_by("-transaction_time").limit(count)

    async def list_in_range_for_user(
        self,
        user_id: int,
        start_date: datetime,
        end_date: datetime,
        limit: int = 201,
    ) -> tuple[list[Transaction], int]:
        # Count total first
        total_count = await Transaction.filter(
            user_id=user_id,
            deleted_at__isnull=True,
            transaction_time__gte=start_date,
            transaction_time__lte=end_date
        ).count()

        # Get rows with limit+1 to detect truncation
        rows = await Transaction.filter(
            user_id=user_id,
            deleted_at__isnull=True,
            transaction_time__gte=start_date,
            transaction_time__lte=end_date
        ).order_by("-transaction_time").limit(limit + 1)

        return rows[:limit], total_count

    async def update_field(self, transaction: Transaction, field: str, value) -> None:
        setattr(transaction, field, value)
        await transaction.save()

    async def soft_delete(self, transaction: Transaction) -> None:
        transaction.deleted_at = datetime.now(timezone.utc)
        await transaction.save()

    async def sum_amount(
        self,
        user_id: int,
        start: datetime,
        end: datetime,
    ) -> float:
        """Sum signed amounts in [start, end] (UTC). Caller passes SGT
        windows converted to UTC via app.utils.timezone.sgt_to_utc()."""
        result = await Transaction.filter(
            user_id=user_id,
            deleted_at__isnull=True,
            transaction_time__gte=start,
            transaction_time__lte=end,
        ).annotate(total=Coalesce(Sum("amount"), 0)).values_list("total", flat=True)
        total = result[0] if result else 0
        return float(total) if total else 0.0

    async def search_transactions(self, user_id: int, merchant_substring: str) -> list[Transaction]:
        return await Transaction.filter(
            user_id=user_id,
            deleted_at__isnull=True,
            merchant__icontains=merchant_substring
        ).order_by("-transaction_time").limit(200)
