from re import IGNORECASE, compile
from typing import Any

from app.services.parsers.base import BankParser


class DBSScanPayParser(BankParser):
    """Parser for DBS NETS Scan & Pay transaction emails.

    Sample body shape::

        Transaction Ref: 627609564051570

        Dear Customer,

        Your NETS Scan & Pay transaction on 03 Oct 12:26 SGT was successful.

        Date & Time: 03 Oct 12:26 SGT
        Amount: S$8.50
        From: DBS/POSB Account ending 5660
        To: MR BEAN

    NETS Scan & Pay is the QR-code debit channel that pulls funds directly
    from the linked DBS/POSB account (or PayLah wallet) — the money never
    passes through a credit card. We bucket it under
    ``DBS_PAYNOW_DEBIT`` so it sits alongside other DBS PayNow-family
    outflows in reporting, but its ``can_parse`` only fires when the email
    explicitly contains "Scan & Pay" / "Scan and Pay" so it doesn't steal
    credit-card or PayNow/PayLah emails from their dedicated parsers.
    """

    name = "DBS_SCANPAY"
    _debit_method = "DBS_PAYNOW_DEBIT"

    # Amount: "Amount: S$8.50" (anchored) or any "S$X" / "SGDX" mention in
    # the body (fallback). The anchored form is tried first by the base
    # `_extract_amount` so the disclaimer text never sneaks in.
    _amount_re = [
        compile(r"Amount:\s*(?:SGD|S\$|\$)\s*([\d,]+\.?\d*)", IGNORECASE),
        compile(r"(?:SGD|S\$|\$)\s*([\d,]+\.?\d*)", IGNORECASE),
    ]

    # Merchant: "To: MR BEAN" — anchor on the preceding
    # "From: DBS/POSB Account ending NNNN" line to avoid the file-preamble
    # "To: ('addr@...',)" header. The merchant line is followed by a
    # newline (and possibly the disclaimer paragraph), so we anchor the
    # capture on `\n` rather than `\(|$` like the PayNow parser — the
    # body here never has the "(MOBILE ending NNNN)" trailing tag.
    _merchant_re = compile(
        r"Account ending \d{4,5}[\s\S]*?\bTo:\s*([^\n\r(]+?)\s*(?=\n|$|\()",
        IGNORECASE,
    )

    # Date: "Date & Time: 03 Oct 12:26 SGT". No year in the body — the
    # base patches it from the email's `Date:` header via _iso_date_re.
    _date_patterns = [
        (
                compile(r"Date\s*&\s*Time:\s*(\d{1,2}\s+\w+\s+\d{1,2}:\d{2})"),
                ["%d %b %H:%M", "%d %B %H:%M"],
            ),
        (
                compile(r"on\s+(\d{1,2}\s+\w+\s+\d{4}\s+\d{1,2}:\d{2})"),
                ["%d %b %Y %H:%M", "%d %B %Y %H:%M"],
            ),
        (
                compile(r"on\s+(\d{1,2}\s+\w+\s+\d{4})"),
                ["%d %B %Y", "%d %b %Y"],
            ),
    ]

    def can_parse(self, email: dict[str, Any]) -> bool:
        body = email.get("body", "") or ""
        if not self._has_amount(body):
            return False
        combined = self._combined_lower(email)
        if self._is_ignored(combined):
            return False
        # DBS bank signal — required so this never claims PayLah/UOB/etc.
        has_dbs = "dbs" in combined or "posb" in combined
        # The defining keyword for this channel. Without it, the email
        # belongs to DBSPayNowParser / DBSCCParser / PayLahParser.
        has_scanpay = ("scan & pay" in combined) or ("scan and pay" in combined)
        # Defer to PayLahParser when the wallet is the funding source —
        # PayLah alerts phrase the same flow as "PayLah! Scan & Pay
        # Transfer" and should be tagged as PAYLAH_DEBIT (which also
        # affects the merchant-from-Wallet rule).
        if "paylah" in combined:
            return False
        return has_dbs and has_scanpay
