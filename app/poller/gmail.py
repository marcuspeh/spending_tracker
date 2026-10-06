import asyncio
import time
from typing import Any, Callable, Coroutine

from imap_tools import AND, MailBox

from app.config.settings import get_settings
from app.database.enums import ImportStatus
from app.logging_setup import client, correlation_id
from app.services.email_ingestion import EmailIngestionService
from app.services.notification import NotificationService
from app.services.parsers import (
    DBSCCParser,
    DBSPayNowParser,
    DBSScanPayParser,
    ParserRegistry,
    PayLahParser,
    TrustCCParser,
    UOBCCParser,
    UOBPayNowParser,
)
from app.telegram.bot import TelegramBot
from app.utils.fx import build_converter
from app.utils.html import strip_html

log = client()


class GmailPoller:
    """Polls Gmail via IMAP for unseen emails and processes them."""

    def __init__(
        self,
        telegram_bot: TelegramBot | None = None,
        on_email_processed: Callable[[ImportStatus], Coroutine[Any, Any, None]] | None = None,
    ):
        self.settings = get_settings()
        self.on_email_processed = on_email_processed
        self.telegram_bot = telegram_bot
        self._running = False
        self._task: asyncio.Task | None = None

        # Set up parser registry — one parser per channel. DBSPayNowParser
        # is registered before PayLahParser so PayNow wins when both
        # signals appear (some PayLah-funded transfers come from PayLah!
        # Alerts but say "PayNow Transfer" in the body). DBSScanPayParser
        # is registered before DBSCCParser so NETS Scan & Pay QR-code
        # debits (which mention "DBS/POSB Account" in the body) are not
        # misrouted to the credit-card parser. TrustCCParser needs an FX
        # converter so overseas transactions come back in SGD.
        fx_converter = build_converter(
            markup_pct=self.settings.fx_markup_pct,
        )
        self.parser_registry = ParserRegistry()
        self.parser_registry.register(UOBCCParser())
        self.parser_registry.register(UOBPayNowParser())
        self.parser_registry.register(DBSScanPayParser())
        self.parser_registry.register(DBSCCParser())
        self.parser_registry.register(DBSPayNowParser())
        self.parser_registry.register(PayLahParser())
        self.parser_registry.register(TrustCCParser(fx_converter=fx_converter))

    async def start(self) -> None:
        """Start the polling loop."""
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        log.info("gmail_poller_started host=%s", self.settings.imap_host)

    async def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("gmail_poller_stopped")

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                await self._poll_once()
            except Exception as e:
                log.error("poll_error error=%s", e)

            await asyncio.sleep(self.settings.poll_interval_seconds)

    async def _poll_once(self) -> None:
        """Poll for unseen emails once."""
        log.debug("poll_start")

        def fetch_unseen():
            with MailBox(self.settings.imap_host, port=self.settings.imap_port) as mailbox:
                mailbox.login(self.settings.imap_username, self.settings.imap_password)
                # Fetch unseen and materialize to list before connection closes
                return list(mailbox.fetch(AND(seen=False), limit=100))

        try:
            emails = await asyncio.to_thread(fetch_unseen)
        except Exception as e:
            log.error("fetch_error error=%s", e)
            return

        email_count = 0
        with correlation_id() as poll_id:
            log.info("poll_cycle_started request_id=%s", poll_id)
            started = time.perf_counter()
            for email in emails:
                email_count += 1
                await self._process_email(email, parent_id=poll_id)

            elapsed_ms = (time.perf_counter() - started) * 1000.0
            log.info(
                "poll_cycle_completed request_id=%s emails_fetched=%d elapsed_ms=%.1f",
                poll_id,
                email_count,
                elapsed_ms,
            )

    async def _process_email(self, email, parent_id: str | None = None) -> None:
        """Process a single email.

        Scoped by its own correlation id (nested under the poll cycle's)
        so every event for one email — parse, LLM tagging, DB insert,
        notification — is grouped in the logging collector.
        """
        # Use the IMAP UID as the dedup key. email.obj is usually None with
        # imap_tools unless you ask for raw, so the Message-ID fallback
        # almost never fires — leading to many empty-string message_ids
        # colliding on the unique constraint.
        message_id = email.uid or ""
        if not message_id:
            with correlation_id() as email_id:
                log.warn(
                    "email_no_uid request_id=%s parent_id=%s subject=%s",
                    email_id,
                    parent_id,
                    email.subject,
                )
                await asyncio.to_thread(self._mark_as_read, email)
            return

        with correlation_id() as email_id:
            started = time.perf_counter()
            log.info(
                "email_started request_id=%s parent_id=%s message_id=%s subject=%s",
                email_id,
                parent_id,
                message_id,
                email.subject,
            )
            status = ImportStatus.SKIPPED
            try:
                notification_service = None
                if self.telegram_bot is not None and self.telegram_bot._app is not None:
                    notification_service = NotificationService(self.telegram_bot._app)
                service = EmailIngestionService(
                    self.parser_registry,
                    notification_service=notification_service,
                )
                status = await service.process_email(
                    self._to_email_dict(email)
                )
                if status in (ImportStatus.SUCCESS, ImportStatus.SKIPPED, ImportStatus.FAILED):
                    await asyncio.to_thread(self._mark_as_read, email)

                if self.on_email_processed:
                    await self.on_email_processed(status)

            except Exception as e:
                await asyncio.to_thread(self._mark_as_read, email)
                log.error(
                    "email_failed request_id=%s message_id=%s elapsed_ms=%.1f error=%s",
                    email_id,
                    message_id,
                    (time.perf_counter() - started) * 1000.0,
                    e,
                )
                return

            elapsed_ms = (time.perf_counter() - started) * 1000.0
            # A FAILED import is a business outcome (unparseable email),
            # not a service fault, so it logs at warn rather than error.
            log_fn = log.warn if status == ImportStatus.FAILED else log.info
            log_fn(
                "email_completed request_id=%s message_id=%s status=%s elapsed_ms=%.1f",
                email_id,
                message_id,
                status.value,
                elapsed_ms,
            )

    @staticmethod
    def _to_email_dict(email) -> dict[str, Any]:
        """Flatten an imap_tools message into the dict the ingestion
        service expects."""
        body = email.text or (strip_html(email.html) if email.html else "") or ""
        return {
            "message_id": email.uid or "",
            "subject": email.subject,
            "body": body,
            "from": email.from_,
            "to": list(email.to),
            "cc": list(email.cc),
            # Email's `Date:` header (tz-aware UTC). Used as a fallback
            # for transactions whose body has no time component (e.g.
            # UOB CC alerts that say "on 04/08/26" but no clock time).
            "date": email.date,
        }

    def _mark_as_read(self, email) -> None:
        """Mark an email as read."""
        try:
            with MailBox(self.settings.imap_host, port=self.settings.imap_port).login(
                self.settings.imap_username,
                self.settings.imap_password,
            ) as mailbox:
                mailbox.flag(email.uid, ["\\Seen"], True)
        except Exception as e:
            log.error("mark_read_error error=%s", e)
