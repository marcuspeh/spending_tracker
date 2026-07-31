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
        if await self.imported_email_repo.exists_by_message_id(message_id):
            existing = await self.imported_email_repo.get_by_message_id(message_id)
            if (
                existing
                and existing.status == ImportStatus.FAILED
                and existing.reason == "UNKNOWN_FORWARDER"
            ):
                return ImportStatus.FAILED
            return existing.status if existing else ImportStatus.SKIPPED

        parser = self.parser_registry.find_parser(email)
        if parser is None:
            await self.imported_email_repo.insert(message_id, ImportStatus.SKIPPED)
            return ImportStatus.SKIPPED

        try:
            parsed = parser.parse(email)
        except ParserError:
            await self.imported_email_repo.insert(message_id, ImportStatus.FAILED, "PARSE_ERROR")
            return ImportStatus.FAILED

        if parsed.payment_method not in PaymentMethod._value2member_map_:
            await self.imported_email_repo.insert(
                message_id, ImportStatus.FAILED, "UNKNOWN_PAYMENT_METHOD"
            )
            return ImportStatus.FAILED

        # Resolve ownership. Trust only `to`/`cc` — these are the addresses
        # the email was actually delivered to. `from` is the bank's domain
        # and is not user-controlled, but it's also not authoritative for
        # ownership, so we ignore it. (SMTP headers are spoofable; trusting
        # them would let an attacker attribute their transaction to any
        # user that owns the spoofed address.)
        candidate_emails: list[str] = []
        for field in ("to", "cc"):
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
            await self.imported_email_repo.insert(
                message_id, ImportStatus.FAILED, "UNKNOWN_FORWARDER"
            )
            return ImportStatus.FAILED

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

        await self.imported_email_repo.insert(message_id, ImportStatus.SUCCESS)
        return ImportStatus.SUCCESS
