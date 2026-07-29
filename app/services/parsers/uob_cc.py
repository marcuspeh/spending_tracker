from typing import Any

from app.services.parsers.base import BankParser


class UOBCCParser(BankParser):
    """Parser for UOB credit-card transaction emails.

    Returns `UOB_CC` for purchases and `UOB_CC_REFUND` for refunds.
    """

    name = "UOB_CC"
    _debit_method = "UOB_CC"
    _refund_method = "UOB_CC_REFUND"

    def can_parse(self, email: dict[str, Any]) -> bool:
        combined = self._combined_lower(email)
        # UOB bank signal + card signal (card can appear in body for forwarded
        # emails where subject is just "UOB - Transaction Alert").
        return "uob" in combined and "card" in combined
