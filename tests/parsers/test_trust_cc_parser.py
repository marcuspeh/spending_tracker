from decimal import Decimal
from datetime import datetime

import pytest

from app.services.parsers.types import ParserError
from app.services.parsers.trust_cc import TrustCCParser
from app.utils.fx import FxConverter
from app.utils.timezone import SGT
from tests.parsers._fx_stub import StubFxConverter


class _RecordFx(FxConverter):
    """Records every conversion request so tests can assert on the call."""

    def __init__(self, sgd_value: Decimal = Decimal("100.00")):
        self.calls: list[tuple[Decimal, str]] = []
        self._sgd_value = sgd_value

    def to_sgd(self, amount: Decimal, currency: str) -> Decimal:
        self.calls.append((amount, currency))
        return self._sgd_value


class TestTrustCCParser:
    def setup_method(self):
        # Default parser uses a stub that returns 0.30 * 1.005 = 0.3015
        # SGD per MYR unit. Tests that care about a specific rate inject
        # their own converter.
        self.parser = TrustCCParser(fx_converter=StubFxConverter())

    def _make_email(self, body: str, subject: str = "Yay! Transaction successful") -> dict:
        return {
            "subject": subject,
            "body": body,
            "from": "Trust <from_us@trustbank.sg>",
            "date": datetime(2026, 9, 5, 7, 3, 5, tzinfo=SGT),
        }

    def test_can_parse_trust_local(self):
        body = (
            "Didn't do this? Please contact us via your Trust App.\n"
            "You've spent SGD 3.00 at STARBUCKS COFFEE@ YTP SINGAPORE SG on 5 Sep 2026 15:03SGT "
            "with Trust Link card. Not you? Alert us via Trust App."
        )
        assert self.parser.can_parse(self._make_email(body)) is True

    def test_can_parse_trust_overseas(self):
        body = (
            "0% FX fees! You've spent MYR 5999.00 using Trust Link card at MACHINES SDN BHD "
            "KUALA LUMPUR MY on 24 Sep 2026 21:23SGT. Not you? Alert us via Trust App."
        )
        assert self.parser.can_parse(self._make_email(body, "Yay! Overseas transaction successful")) is True

    def test_cannot_parse_non_trust(self):
        body = "You've spent SGD 3.00 at FOO with some other card."
        assert self.parser.can_parse(self._make_email(body)) is False

    def test_sgd_amount_passes_through_unchanged(self):
        body = (
            "You've spent SGD 7.50 at COFFEE SINGAPORE SG on 5 Sep 2026 15:03SGT with "
            "Trust Link card. Alert us via Trust App."
        )
        result = self.parser.parse(self._make_email(body))
        assert result.amount == Decimal("7.50")
        assert result.payment_method == "TRUST_CC"

    def test_foreign_currency_is_converted_via_fx_converter(self):
        record = _RecordFx(sgd_value=Decimal("1234.56"))
        parser = TrustCCParser(fx_converter=record)
        body = (
            "You've spent MYR 5999.00 using Trust Link card at MACHINES SDN BHD KUALA LUMPUR "
            "MY on 24 Sep 2026 21:23SGT. Alert us via Trust App."
        )
        result = parser.parse(self._make_email(body, "Yay! Overseas transaction successful"))
        # The parser must hand the *original* amount and currency to the
        # converter, then take whatever SGD value the converter returns.
        assert record.calls == [(Decimal("5999.00"), "MYR")]
        assert result.amount == Decimal("1234.56")
        assert result.payment_method == "TRUST_CC"

    def test_missing_fx_converter_raises_for_foreign_currency(self):
        parser = TrustCCParser()  # no fx_converter
        body = (
            "You've spent MYR 100.00 using Trust Link card at MACHINES SDN BHD KUALA LUMPUR "
            "MY on 24 Sep 2026 21:23SGT. Alert us via Trust App."
        )
        with pytest.raises(ParserError, match="FX converter"):
            parser.parse(self._make_email(body, "Yay! Overseas transaction successful"))