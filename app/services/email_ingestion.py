from typing import Any

from app.database.enums import ImportStatus, PaymentMethod
from app.database.repositories.imported_email import ImportedEmailRepository
from app.database.repositories.transaction import TransactionRepository
from app.database.repositories.user_email import UserEmailRepository
from app.services.parsers.base import ParserError
from app.services.parsers.registry import ParserRegistry
from app.utils.timezone import sgt_to_utc


class EmailIngestionService:
    """Service for processing incoming emails and extracting transactions."""

    def __init__(
        self,
        parser_registry: ParserRegistry,
    ):
        self.parser_registry = parser_registry
        self.transaction_repo = TransactionRepository()
        self.user_email_repo = UserEmailRepository()
        self.imported_email_repo = ImportedEmailRepository()

    async def process_email(self, email: dict[str, Any]) -> ImportStatus:
        """Process an email and extract transaction if possible.

        Args:
            email: Email dict with 'message_id', 'subject', 'body', 'from', etc.

        Returns:
            ImportStatus indicating the result of processing.
        """
        message_id = email.get("message_id", "")

        # Check for duplicate
        if await self.imported_email_repo.exists_by_message_id(message_id):
            existing = await self.imported_email_repo.get_by_message_id(message_id)
            if existing and existing.status == ImportStatus.FAILED and existing.reason == "UNKNOWN_FORWARDER":
                # Re-encountering an unknown forwarder - mark as seen but don't reprocess
                return ImportStatus.FAILED
            return existing.status if existing else ImportStatus.SKIPPED

        # Try to find a parser
        parser = self.parser_registry.find_parser(email)
        if parser is None:
            # No parser matched - SKIPPED
            await self.imported_email_repo.insert(message_id, ImportStatus.SKIPPED)
            return ImportStatus.SKIPPED

        # Try to parse
        try:
            parsed = parser.parse(email)
        except ParserError:
            # Parser matched but failed - FAILED
            await self.imported_email_repo.insert(message_id, ImportStatus.FAILED, "PARSE_ERROR")
            return ImportStatus.FAILED

        # Resolve ownership via any sender/recipient address. For forwarded
        # emails the parser mailbox will appear in `to`/`cc`, and the
        # forwarder's address (X-Forwarded-For, or the original To for
        # Gmail manual forwards) may appear in any of the three fields.
        candidate_emails: list[str] = []
        for field in ("from", "to", "cc"):
            value = email.get(field)
            if isinstance(value, str):
                candidate_emails.append(value)
            elif isinstance(value, (list, tuple)):
                candidate_emails.extend(v for v in value if v)

        user_email = None
        for candidate in candidate_emails:
            user_email = await self.user_email_repo.find_by_email(candidate)
            if user_email:
                break

        if not user_email:
            # No matching user email - FAILED
            await self.imported_email_repo.insert(message_id, ImportStatus.FAILED, "UNKNOWN_FORWARDER")
            return ImportStatus.FAILED

        # Insert transaction
        payment_method = PaymentMethod(parsed.payment_method)
        transaction_time_utc = sgt_to_utc(parsed.transaction_time)

        await self.transaction_repo.insert(
            user_id=user_email.user_id,
            amount=float(parsed.amount),
            merchant=parsed.merchant,
            payment_method=payment_method,
            transaction_time=transaction_time_utc,
            description=parsed.description,
        )

        # Record successful import
        await self.imported_email_repo.insert(message_id, ImportStatus.SUCCESS)
        return ImportStatus.SUCCESS
