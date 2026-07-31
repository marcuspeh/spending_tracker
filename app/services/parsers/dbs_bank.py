from re import IGNORECASE, compile
from typing import Any

from app.services.parsers.base import BankParser


class DBSBankParser(BankParser):
    """Parser for DBS/POSB bank-to-bank transfer emails (FAST / GIRO / internal).

    These come from the same `ibanking.alert@dbs.com` sender as PayNow
    notifications but use different channel words — ``via FAST`` for
    incoming credits, ``Funds Transfer to Other DBS/POSB account`` for
    outgoing debits.

    Sample body shapes::

        # Credit (FAST incoming)
        You have received SGD 10.35 via FAST transfer on 03 Jun 2026 00:13 SGT.
        From: JANE DOE
        To:   Your DBS/ POSB account ending 5660

        # Debit (outgoing to another bank/DBS/POSB account)
        Your Funds Transfer to Other DBS/POSB account dated 03 Mar has been completed.
        Date & Time: 31 Jul 00:13 (SGT)
        Amount: SGD1.00
        From: POSB Passbook Savings Account A/C ending 5660
        To:   IBKR (A/C ending 0775)

    Returns ``DBS_BANK_TRANSFER_CREDIT`` for incoming and
    ``DBS_BANK_TRANSFER_DEBIT`` for outgoing.
    """

    name = "DBS_BANK"
    _debit_method = "DBS_BANK_TRANSFER_DEBIT"
    _credit_method = "DBS_BANK_TRANSFER_CREDIT"

    # Merchant / counterparty: "From: JANE DOE" (credit) or
    # "To: IBKR (A/C ending 0775)" (debit). We pick the regex by direction
    # in `_extract_merchant` below; both anchors on the body's
    # "Dear Customer," / "Date & Time:" / "Amount:" markers so we don't
    # grab the file-preamble "To: ('addr@...',)" line.
    _merchant_re_debit = compile(
        r"(?:Dear Customer,|Date\s*&\s*Time:|Amount:\s*(?:SGD|S\$|\$))"
        r"[\s\S]*?\bTo:\s*([^\n\r]+)",
        IGNORECASE,
    )
    _merchant_re_credit = compile(
        r"(?:Dear Customer,|Date\s*&\s*Time:|Amount:\s*(?:SGD|S\$|\$))"
        r"[\s\S]*?\bFrom:\s*([^\n\r]+)",
        IGNORECASE,
    )

    def _extract_merchant(
        self, body: str, is_credit: bool = False, is_refund: bool = False
    ) -> str:
        regex = self._merchant_re_credit if is_credit else self._merchant_re_debit
        m = regex.search(body)
        if not m:
            return self.name or "Transaction"
        return m.group(1).strip()

    # Dates appear in body as:
    #   "on 03 Jun 2026 00:13 SGT"  (FAST credit)
    #   "dated 03 Mar"              (debit header, no year)
    #   "Date & Time: 31 Jul 00:13 (SGT)"
    _date_patterns = [
        (compile(r"on\s+(\d{1,2}\s+\w+\s+\d{4}\s+\d{1,2}:\d{2})"),
         ["%d %b %Y %H:%M", "%d %B %Y %H:%M"]),
        (compile(r"on\s+(\d{1,2}\s+\w+\s+\d{4})"),
         ["%d %B %Y", "%d %b %Y"]),
        (compile(r"dated\s+(\d{1,2}\s+\w+\s+\d{4})"),
         ["%d %B %Y", "%d %b %Y"]),
        (compile(r"dated\s+(\d{1,2}\s+\w+\s+\d{2})"),
         ["%d %b %y", "%d %B %y"]),
        (compile(r"\bDate\s*&\s*Time:\s*(\d{1,2}\s+\w+\s+\d{1,2}:\d{2})"),
         ["%d %b %H:%M", "%d %B %H:%M"]),
    ]

    def can_parse(self, email: dict[str, Any]) -> bool:
        body = email.get("body", "") or ""
        if not self._has_amount(body):
            return False
        combined = self._combined_lower(email)
        if self._is_ignored(combined):
            return False

        # Only DBS / POSB traffic.
        if "dbs" not in combined and "posb" not in combined:
            return False

        # Exclude PayNow — that has its own parser.
        if "paynow" in combined:
            return False

        # Exclude credit-card traffic (DBS CC has its own parser).
        if (
            "card" in combined
            and "transaction alert" in combined
            and ("dbs/posb card ending" in combined or "card transaction" in combined)
        ):
            return False

        # Must mention a bank-to-bank channel: FAST (incoming) or
        # "Funds Transfer to Other" / "Other DBS/POSB account" (outgoing).
        bank_signals = (
            "via fast",
            "via giro",
            "funds transfer to other",
            "other dbs/posb account",
        )
        return any(s in combined for s in bank_signals)
