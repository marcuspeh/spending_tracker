from typing import Any

from app.services.parsers.base import BankParser


class DBSCCParser(BankParser):
    """Parser for DBS/POSB credit-card transaction emails.

    Returns `DBS_CC` for purchases and `DBS_CC_REFUND` for refunds.
    """

    name = "DBS_CC"
    _debit_method = "DBS_CC"
    _refund_method = "DBS_CC_REFUND"
    # "To: APPLE.COM/BILL" — but skip email-style recipients like
    # "To: <HKMPEH@gmail.com>" that appear in forwarded-message headers.
    _merchant_pattern = r"^To:\s*([^\n\r<]+)$"

    def can_parse(self, email: dict[str, Any]) -> bool:
        combined = self._combined_lower(email)
        subject_lower = email.get("subject", "").lower()
        body_lower = email.get("body", "").lower()

        if "dbs" not in combined and "posb" not in combined:
            return False

        if "paynow" in combined:
            return False

        # Strong DBS signals: card-alert subjects always come from DBS.
        if "card transaction alert" in subject_lower or "card refund alert" in subject_lower:
            return True

        # Otherwise require DBS/POSB + card/POSB together.
        has_dbs = "dbs" in combined or "posb" in combined
        has_card_signal = (
            "card" in subject_lower
            or "card" in body_lower
            or "posb" in combined
            or "card transaction" in combined
        )
        return has_dbs and has_card_signal
