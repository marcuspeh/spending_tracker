from typing import Any

from app.services.parsers.base import BankParser


class DBSPayNowParser(BankParser):
    """Parser for DBS/POSB PayNow transaction emails.

    Returns `DBS_PAYNOW_DEBIT` for outgoing and `DBS_PAYNOW_CREDIT` for
    incoming transfers.

    Note: PayNow wins over PayLah when both signals appear — some PayLah-
    funded transfers come from PayLah! Alerts but the body explicitly says
    "PayNow Transfer", and those are PayNow debits.
    """

    name = "DBS_PAYNOW"
    _debit_method = "DBS_PAYNOW_DEBIT"
    _credit_method = "DBS_PAYNOW_CREDIT"
    _merchant_pattern = r"(?:to|from|via|payment to)\s+([A-Za-z0-9\s]+?)(?:\s+on\s+|\s+\d|\s*$)"

    def can_parse(self, email: dict[str, Any]) -> bool:
        combined = self._combined_lower(email)
        # DBS bank signal AND PayNow channel signal.
        has_dbs = "dbs" in combined or "posb" in combined
        has_paynow = "paynow" in combined
        return has_dbs and has_paynow
