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
    ) -> ImportedEmail:
        imported_email = await ImportedEmail.create(
            message_id=message_id,
            status=status,
            reason=reason,
        )
        return imported_email
