from tortoise import fields
from tortoise.models import Model


class User(Model):
    id = fields.IntField(pk=True, auto_now_add=True)
    telegram_chat_id = fields.BigIntField(unique=True)
    name = fields.CharField(max_length=255)
    active = fields.BooleanField(default=True)
    created_at = fields.DatetimeField(db_default=fields.Now())
    updated_at = fields.DatetimeField(db_default=fields.Now())
    deleted_at = fields.DatetimeField(null=True)

    class Meta:
        table = "users"
        ordering = ["-created_at"]

    def __str__(self):
        return f"User(id={self.id}, name={self.name})"
