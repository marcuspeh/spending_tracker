from tortoise import fields
from tortoise.models import Model


class MerchantTagCache(Model):
    """Persistent cache of merchant → tag mappings.

    Populated only by successful LLM responses. Read-only from the bot's
    perspective: the tagger is the sole writer. To change a row, modify
    MySQL directly.

    Class name is still ``MerchantCategoryCache`` in the DB; the
    Python class was renamed to reflect the new column name.
    """

    merchant = fields.CharField(max_length=255, pk=True)
    tag = fields.CharField(max_length=32)
    # Future-proofing: lets us distinguish "set by LLM" from "set by
    # manual SQL override" if we ever add the latter.
    source = fields.CharField(max_length=16, default="llm")
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "merchant_category_cache"

    def __str__(self) -> str:
        return f"MerchantTagCache(merchant={self.merchant!r}, tag={self.tag!r})"