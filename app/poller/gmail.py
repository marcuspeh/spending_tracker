import asyncio
from typing import Any, Callable, Coroutine

import structlog
from imap_tools import AND, MailBox

from app.config.settings import get_settings
from app.database.enums import ImportStatus
from app.services.email_ingestion import EmailIngestionService
from app.services.parsers import (
    DBSCCParser,
    DBSPayNowParser,
    ParserRegistry,
    PayLahParser,
    UOBCCParser,
    UOBPayNowParser,
)

logger = structlog.get_logger()


class GmailPoller:
    """Polls Gmail via IMAP for unseen emails and processes them."""

    def __init__(
        self,
        on_email_processed: Callable[[ImportStatus], Coroutine[Any, Any, None]] | None = None,
    ):
        self.settings = get_settings()
        self.on_email_processed = on_email_processed
        self._running = False
        self._task: asyncio.Task | None = None

        # Set up parser registry — one parser per channel. DBSPayNowParser is
        # registered before PayLahParser so PayNow wins when both signals appear
        # (some PayLah-funded transfers come from PayLah! Alerts but say
        # "PayNow Transfer" in the body).
        self.parser_registry = ParserRegistry()
        self.parser_registry.register(UOBCCParser())
        self.parser_registry.register(UOBPayNowParser())
        self.parser_registry.register(DBSCCParser())
        self.parser_registry.register(DBSPayNowParser())
        self.parser_registry.register(PayLahParser())

    async def start(self) -> None:
        """Start the polling loop."""
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("gmail_poller_started", host=self.settings.imap_host)

    async def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("gmail_poller_stopped")

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                await self._poll_once()
            except Exception as e:
                logger.error("poll_error", error=str(e))

            await asyncio.sleep(self.settings.poll_interval_seconds)

    async def _poll_once(self) -> None:
        """Poll for unseen emails once."""
        logger.debug("poll_start")

        def fetch_unseen():
            with MailBox(self.settings.imap_host, port=self.settings.imap_port) as mailbox:
                mailbox.login(self.settings.imap_username, self.settings.imap_password)
                # Fetch unseen and materialize to list before connection closes
                return list(mailbox.fetch(AND(seen=False), limit=100))

        try:
            emails = await asyncio.to_thread(fetch_unseen)
        except Exception as e:
            logger.error("fetch_error", error=str(e))
            return

        email_count = 0
        for email in emails:
            email_count += 1
            await self._process_email(email)

        logger.info("poll_end", emails_fetched=email_count)

    async def _process_email(self, email) -> None:
        """Process a single email."""
        message_id = email.uid or email.message_id

        logger.debug(
            "email_fetched",
            message_id=message_id,
            subject=email.subject,
        )

        # Convert email to dict format
        email_dict = {
            "message_id": message_id,
            "subject": email.subject,
            "body": email.text or "",
            "from": email.from_,
        }

        try:
            service = EmailIngestionService(self.parser_registry)
            status = await service.process_email(email_dict)

            # Handle mark-as-read logic
            if status == ImportStatus.SUCCESS:
                await asyncio.to_thread(self._mark_as_read, email)
                logger.info("email_processed", message_id=message_id, status=status.value)
            elif status == ImportStatus.FAILED:
                # Check if it's UNKNOWN_FORWARDER (needs second encounter to mark read)
                logger.warning("email_failed", message_id=message_id, status=status.value)
            else:  # SKIPPED
                logger.info("email_skipped", message_id=message_id)

            if self.on_email_processed:
                await self.on_email_processed(status)

        except Exception as e:
            logger.error("email_error", message_id=message_id, error=str(e))

    def _mark_as_read(self, email) -> None:
        """Mark an email as read."""
        try:
            with MailBox(self.settings.imap_host, port=self.settings.imap_port).login(
                self.settings.imap_username,
                self.settings.imap_password,
            ) as mailbox:
                mailbox.flag(email.uid, ["\\Seen"], True)
        except Exception as e:
            logger.error("mark_read_error", error=str(e))
