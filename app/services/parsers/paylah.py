from typing import Any

from app.services.parsers.base import BankParser


class PayLahParser(BankParser):
    """Parser for DBS PayLah transaction emails.

    PayLah only sends outgoing payment notifications (no incoming email), so
    this parser always returns `PAYLAH_DEBIT` with a positive amount — even
    when the body contains words like "received" or "credit", PayLah is
    never the destination.
    """

    name = "PAYLAH"
    _debit_method = "PAYLAH_DEBIT"

    def can_parse(self, email: dict[str, Any]) -> bool:
        combined = self._combined_lower(email)
        # PayLah channel signal — but reject when PayNow is also present, since
        # PayLah-funded PayNow transfers ("We refer to a PayNow Transfer") are
        # claimed by DBSPayNowParser, not this one.
        if "paynow" in combined:
            return False
        return "paylah" in combined

    def _force_positive(self) -> bool:
        return True
