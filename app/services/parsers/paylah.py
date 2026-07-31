from re import IGNORECASE, MULTILINE, compile
from typing import Any

from app.services.parsers.base import BankParser


class PayLahParser(BankParser):
    """Parser for DBS PayLah transaction emails.

    Sample body shape::

        We refer to your PayLah! Scan & Pay Transfer dated 16 Jul.
        Date & Time: 16 Jul 10:35 (SGT)
        Amount: SGD2000.00
        From: PayLah! Wallet (Mobile ending 8352)
        To:   CHOCFIN PTE. LTD. - CHOCOLATE CLIENTS AC

    PayLah only sends outgoing payment notifications (no incoming email), so
    this parser always returns `PAYLAH_DEBIT` with a positive amount — even
    when the body contains words like "received" or "credit", PayLah is
    never the destination.
    """

    name = "PAYLAH"
    _debit_method = "PAYLAH_DEBIT"

    # Merchant is the "To: <payee>" line in the body. To avoid picking up
    # the file-preamble "To: ('addr@...',)" header, anchor on the preceding
    # "From: ... Wallet ..." line that uniquely identifies the body section.
    _merchant_re = compile(
        r"Wallet[^\n]*\n[\s\S]*?To:\s*\n?\s*(.+?)\s*$",
        IGNORECASE | MULTILINE,
    )

    # Date appears as "Date & Time: 16 Jul 10:35 (SGT)". No year in the
    # body — the base patches it from the email's `Date:` header via
    # _iso_date_re.
    _date_patterns = [
        (compile(r"Date\s*&\s*Time:\s*(\d{1,2}\s+\w+\s+\d{1,2}:\d{2})"),
         ["%d %b %H:%M", "%d %B %H:%M"]),
    ]

    def can_parse(self, email: dict[str, Any]) -> bool:
        body = email.get("body", "") or ""
        if not self._has_amount(body):
            return False
        combined = self._combined_lower(email)
        if self._is_ignored(combined):
            return False
        # PayNow wins over PayLah when both signals appear — PayLah-funded
        # PayNow transfers are claimed by DBSPayNowParser.
        if "paynow" in combined:
            return False
        return "paylah" in combined

    def _force_positive(self) -> bool:
        return True
