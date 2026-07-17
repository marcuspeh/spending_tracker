from tortoise import fields
from tortoise.models import Model


class UserEmail(Model):
    id = fields.IntField(pk=True, auto_now_add=True)
    user_id = fields.IntField()
    email = fields.CharField(max_length=320, unique=True)
    created_at = fields.DatetimeField(db_default=fields.Now())
    updated_at = fields.DatetimeField(db_default=fields.Now())
    deleted_at = fields.DatetimeField(null=True)

    class Meta:
        table = "user_emails"
        ordering = ["-created_at"]

    def __str__(self):
        return f"UserEmail(id={self.id}, email={self.email})"
