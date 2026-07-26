from tortoise.exceptions import IntegrityError

from app.database.enums import ImportStatus
from app.database.models.imported_email import ImportedEmail


class ImportedEmailRepository:
    async def exists_by_message_id(self, message_id: str) -> bool:
        return await ImportedEmail.filter(message_id=message_id).exists()

    async def get_by_message_id(self, message_id: str) -> ImportedEmail | None:
        return await ImportedEmail.filter(message_id=message_id).first()

    async def insert(
        self,
        message_id: str,
        status: ImportStatus,
        reason: str | None = None,
    ) -> ImportedEmail | None:
        """Insert an ImportedEmail record.

        Returns None if a record with this message_id already exists (the
        unique constraint on message_id will raise IntegrityError). Callers
        should treat this as "already seen" rather than crashing.
        """
        try:
            return await ImportedEmail.create(
                message_id=message_id,
                status=status,
                reason=reason,
            )
        except IntegrityError:
            return None
