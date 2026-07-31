from re import IGNORECASE, compile
from typing import Any

from app.services.parsers.base import BankParser


class DBSPayNowParser(BankParser):
    """Parser for DBS/POSB PayNow transaction emails.

    Sample body shapes::

        # Credit
        You have received SGD 40.00 via PayNow on 07 Jul 2026 09:45 SGT.
        From: JOHN DOE
        To:   Your DBS/ POSB account ending 5630

        # Debit
        Amount: SGD10.00
        From: PayLah! Wallet (Mobile ending 8352)
        To:   JOHN DOE (Mobile ending 2453)

    Returns `DBS_PAYNOW_DEBIT` for outgoing and `DBS_PAYNOW_CREDIT` for
    incoming transfers.

    Note: PayNow wins over PayLah when both signals appear — some PayLah-
    funded transfers come from PayLah! Alerts but the body explicitly says
    "PayNow Transfer", and those are PayNow debits.
    """

    name = "DBS_PAYNOW"
    _debit_method = "DBS_PAYNOW_DEBIT"
    _credit_method = "DBS_PAYNOW_CREDIT"

    # Amount may appear as "Amount: SGD10.00" (debited-format) or as the
    # inline "received SGD 40.00 via PayNow" / "sent ... payment of $25.00"
    # phrasing. The shared "SGD|S$|\\s*([\d,]+\\.?\\d*)" matches both.

    # Merchant line: "To: CHUA CHEW (MOBILE ending 2453)" (debit) or
    # "From: TOM TAN" (credit). We pick the regex by direction in
    # `_extract_merchant` below. Both anchor on the body's
    # "Transaction Ref:" / "Dear Customer," / "Amount: SGD..." markers so
    # we don't grab the file-preamble "To: ('addr@...',)" line.
    _merchant_re_debit = compile(
        r"(?:Transaction Ref:|Dear Customer,|Amount:\s*(?:SGD|S\$|\$))"
        r"[\s\S]*?\bTo:\s*([^\n\r(]+?)\s*(?=\(|$)",
        IGNORECASE,
    )
    _merchant_re_credit = compile(
        r"(?:Transaction Ref:|Dear Customer,|Amount:\s*(?:SGD|S\$|\$))"
        r"[\s\S]*?\bFrom:\s*([^\n\r]+)",
        IGNORECASE,
    )

    def _extract_merchant(self, body: str, is_credit: bool = False, is_refund: bool = False) -> str:
        regex = self._merchant_re_credit if is_credit else self._merchant_re_debit
        m = regex.search(body)
        if not m:
            return self.name or "Transaction"
        return m.group(1).strip()

    # Dates appear in body as:
    #   "on 07 Jul 2026 09:45 SGT"  (credit, 4-digit year)
    #   "dated 16 Jul"              (debit header, no year)
    #   "Date & Time: 31 Jul 00:13 (SGT)"
    # 4-digit-year form is tried first so we land on the right year. When
    # the body has no year, the base patches it from the email's `Date:`
    # header via _iso_date_re.
    _date_patterns = [
        (
            compile(r"on\s+(\d{1,2}\s+\w+\s+\d{4}\s+\d{1,2}:\d{2})"),
            ["%d %b %Y %H:%M", "%d %B %Y %H:%M"],
        ),
        (compile(r"on\s+(\d{1,2}\s+\w+\s+\d{4})"), ["%d %B %Y", "%d %b %Y"]),
        (compile(r"dated\s+(\d{1,2}\s+\w+\s+\d{4})"), ["%d %B %Y", "%d %b %Y"]),
        (compile(r"dated\s+(\d{1,2}\s+\w+\s+\d{2})"), ["%d %b %y", "%d %B %y"]),
        (
            compile(r"\bDate\s*&\s*Time:\s*(\d{1,2}\s+\w+\s+\d{1,2}:\d{2})"),
            ["%d %b %H:%M", "%d %B %H:%M"],
        ),
    ]

    def can_parse(self, email: dict[str, Any]) -> bool:
        body = email.get("body", "") or ""
        if not self._has_amount(body):
            return False
        combined = self._combined_lower(email)
        if self._is_ignored(combined):
            return False
        has_dbs = "dbs" in combined or "posb" in combined
        has_paynow = "paynow" in combined
        return has_dbs and has_paynow
