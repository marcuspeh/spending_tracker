from tortoise import fields
from tortoise.models import Model

from app.database.enums import ImportStatus


class ImportedEmail(Model):
    id = fields.IntField(pk=True, auto_now_add=True)
    message_id = fields.CharField(max_length=191, unique=True)
    status = fields.CharEnumField(ImportStatus)
    reason = fields.CharField(max_length=255, null=True)
    created_at = fields.DatetimeField(db_default=fields.Now())

    class Meta:
        table = "imported_emails"
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"ImportedEmail(id={self.id}, message_id={self.message_id[:30]}, status={self.status})"
        )
