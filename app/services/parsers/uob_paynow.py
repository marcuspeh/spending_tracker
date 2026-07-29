from typing import Any

from app.services.parsers.base import BankParser


class UOBPayNowParser(BankParser):
    """Parser for UOB PayNow transaction emails.

    Returns `UOB_PAYNOW_DEBIT` for outgoing and `UOB_PAYNOW_CREDIT` for
    incoming transfers.
    """

    name = "UOB_PAYNOW"
    _debit_method = "UOB_PAYNOW_DEBIT"
    _credit_method = "UOB_PAYNOW_CREDIT"
    _merchant_pattern = r"(?:to|from|via|payment to)\s+([A-Za-z0-9\s]+?)(?:\s+on\s+|\s+\d|\s*$)"

    def can_parse(self, email: dict[str, Any]) -> bool:
        combined = self._combined_lower(email)
        # UOB bank signal AND PayNow channel signal.
        return "uob" in combined and "paynow" in combined
