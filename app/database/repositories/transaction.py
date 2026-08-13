from datetime import datetime, timezone
from decimal import Decimal

from tortoise.functions import Coalesce, Sum
from tortoise.queryset import QuerySet

from app.database.enums import PaymentMethod
from app.database.models.transaction import Transaction


def _normalize_tag(tag: str | None) -> str | None:
    """Lowercase + strip a tag. ``None`` and '' both return ``None``."""
    if tag is None:
        return None
    cleaned = tag.strip().lower()
    return cleaned or None


class TransactionRepository:
    async def insert(
        self,
        user_id: int,
        amount: float | Decimal | None,
        merchant: str,
        payment_method: PaymentMethod,
        transaction_time: datetime,
        description: str | None = None,
        tag: str | None = None,
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
            tag=_normalize_tag(tag),
        )
        return transaction

    async def get_by_id_for_user(self, transaction_id: int, user_id: int) -> Transaction | None:
        return await Transaction.filter(
            id=transaction_id, user_id=user_id, deleted_at__isnull=True
        ).first()

    def _base_filter(self, user_id: int) -> QuerySet:
        """Build the standard ``user_id + not-deleted`` filter."""

        return Transaction.filter(user_id=user_id, deleted_at__isnull=True)

    async def list_latest_for_user(
        self, user_id: int, count: int = 10
    ) -> list[Transaction]:
        # Order by transaction_time descending; tie-break by id so two
        # transactions with the same timestamp come back in a stable
        # order (newest insertion first).
        return (
            await self._base_filter(user_id)
            .order_by("-transaction_time", "-id")
            .limit(count)
        )

    async def list_in_range_for_user(
        self,
        user_id: int,
        start_date: datetime,
        end_date: datetime,
        limit: int = 201,
    ) -> tuple[list[Transaction], int]:
        window = self._base_filter(user_id).filter(
            transaction_time__gte=start_date,
            transaction_time__lte=end_date,
        )
        total_count = await window.count()

        rows = (
            await window.order_by("-transaction_time").limit(limit + 1)
        )

        return rows[:limit], total_count

    async def update_field(self, transaction: Transaction, field: str, value) -> None:
        if field == "tag":
            value = _normalize_tag(value)
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
        result = (
            await self._base_filter(user_id)
            .filter(
                transaction_time__gte=start,
                transaction_time__lte=end,
            )
            .annotate(total=Coalesce(Sum("amount"), 0))
            .values_list("total", flat=True)
        )
        total = result[0] if result else 0
        return float(total) if total else 0.0

    async def search_transactions(
        self,
        user_id: int,
        merchant_substring: str,
    ) -> list[Transaction]:
        return (
            await self._base_filter(user_id)
            .filter(merchant__icontains=merchant_substring)
            .order_by("-transaction_time")
            .limit(200)
        )