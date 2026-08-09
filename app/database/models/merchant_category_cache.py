from tortoise import fields
from tortoise.models import Model


class MerchantCategoryCache(Model):
    """Persistent cache of merchant → category mappings.

    Populated only by successful LLM responses. Read-only from the bot's
    perspective: the categorizer is the sole writer. To change a row,
    modify MySQL directly.
    """

    merchant = fields.CharField(max_length=255, pk=True)
    category = fields.CharField(max_length=32)
    # Future-proofing: lets us distinguish "set by LLM" from "set by
    # manual SQL override" if we ever add the latter.
    source = fields.CharField(max_length=16, default="llm")
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "merchant_category_cache"

    def __str__(self) -> str:
        return f"MerchantCategoryCache(merchant={self.merchant!r}, category={self.category!r})"
