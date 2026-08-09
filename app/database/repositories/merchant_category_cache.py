"""Repository for the merchant → category cache."""

from datetime import datetime, timezone

from app.database.models.merchant_category_cache import MerchantCategoryCache


class MerchantCategoryCacheRepository:
    """Read-through / write-through cache for merchant categorizations.

    The cache is read-only from the bot's perspective: the only writer
    is :class:`app.services.categorizer.categorize` after a successful
    LLM response. To modify a row, edit MySQL directly.
    """

    async def get(self, merchant_key: str) -> str | None:
        """Return the cached category for ``merchant_key``, or None.

        ``merchant_key`` must already be normalized (trimmed +
        lowercased). Returns ``None`` on miss.
        """
        if not merchant_key:
            return None
        row = await MerchantCategoryCache.filter(merchant=merchant_key).first()
        return row.category if row else None

    async def upsert(self, merchant_key: str, category: str) -> None:
        """Insert or update the cache entry for ``merchant_key``.

        Called only on successful LLM responses. Idempotent: re-running
        with the same inputs overwrites the existing row.
        """
        if not merchant_key or not category:
            return
        await MerchantCategoryCache.update_or_create(
            merchant=merchant_key,
            defaults={
                "category": category,
                "source": "llm",
                "updated_at": datetime.now(timezone.utc),
            },
        )
