"""Stub FX converter for parser tests.

The real converter scrapes Google Finance; tests use this in-memory
version so they don't need network access. The rates are chosen so
MYR → SGD ends up at a clean, easy-to-reason-about value when the 0.5%
markup is applied: 5999.00 MYR * 0.30 * 1.005 = 1808.6985 ≈ 1808.70 SGD.
"""

from decimal import Decimal

from app.utils.fx import FxConverter


class StubFxConverter(FxConverter):
    """Returns a fixed per-currency rate × (1 + markup)."""

    def __init__(self, markup_pct: float = 0.005, rates: dict[str, Decimal] | None = None):
        # Rate is "1 <currency> = X SGD" before markup. Default matches
        # ~MYR ≈ 0.30 SGD so the overseas test amount converts cleanly.
        self._markup = Decimal(str(markup_pct))
        self._rates = rates or {"MYR": Decimal("0.30")}

    def to_sgd(self, amount: Decimal, currency: str) -> Decimal:
        cur = currency.upper()
        if cur == "SGD":
            return amount
        rate = self._rates.get(cur)
        if rate is None:
            raise ValueError(f"StubFxConverter has no rate for {cur}")
        converted = (amount * rate * (Decimal(1) + self._markup)).quantize(
            Decimal("0.01"), rounding="ROUND_HALF_UP"
        )
        return converted