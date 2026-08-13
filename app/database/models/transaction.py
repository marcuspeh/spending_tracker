from tortoise import fields
from tortoise.models import Model

from app.database.enums import PaymentMethod


class Transaction(Model):
    id = fields.IntField(pk=True, auto_now_add=True)
    user_id = fields.IntField()
    amount = fields.DecimalField(max_digits=10, decimal_places=2)
    merchant = fields.CharField(max_length=255)
    payment_method = fields.CharEnumField(PaymentMethod)
    description = fields.TextField(null=True)
    tag = fields.CharField(max_length=32, null=True, db_index=True)
    transaction_time = fields.DatetimeField()
    created_at = fields.DatetimeField(db_default=fields.Now())
    updated_at = fields.DatetimeField(db_default=fields.Now())
    deleted_at = fields.DatetimeField(null=True)

    class Meta:
        table = "transactions"
        ordering = ["-transaction_time"]

    def __str__(self):
        return f"Transaction(id={self.id}, amount={self.amount}, merchant={self.merchant})"
