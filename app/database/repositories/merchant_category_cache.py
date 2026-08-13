"""Repository for the merchant → tag cache.

Class names keep the old ``MerchantCategoryCache`` reference so the DB
table name and historical code don't have to change at the SQL level —
only the Python class name and the cache field name did.
"""

from datetime import datetime, timezone

from app.database.models.merchant_category_cache import MerchantTagCache


class MerchantTagCacheRepository:
    """Read-through / write-through cache for merchant tags.

    The cache is read-only from the bot's perspective: the only writer
    is the tagger after a successful LLM response. To modify a row,
    edit MySQL directly.
    """

    async def get(self, merchant_key: str) -> str | None:
        """Return the cached tag for ``merchant_key``, or None.

        ``merchant_key`` must already be normalized (trimmed +
        lowercased). Returns ``None`` on miss.
        """
        if not merchant_key:
            return None
        row = await MerchantTagCache.filter(merchant=merchant_key).first()
        return row.tag if row else None

    async def upsert(self, merchant_key: str, tag: str) -> None:
        """Insert or update the cache entry for ``merchant_key``.

        Called only on successful LLM responses. Idempotent: re-running
        with the same inputs overwrites the existing row.
        """
        if not merchant_key or not tag:
            return
        await MerchantTagCache.update_or_create(
            merchant=merchant_key,
            defaults={
                "tag": tag,
                "source": "llm",
                "updated_at": datetime.now(timezone.utc),
            },
        )