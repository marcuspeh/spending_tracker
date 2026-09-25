"""Foreign-currency → SGD conversion helpers.

The only provider today is :class:`GoogleFinanceScraper`, which scrapes
the rendered rate from ``https://www.google.com/finance/quote/<CUR>-SGD``.
No API key required; the cookie ``CONSENT=YES+`` is sent so Google
returns the full page instead of a 302 to the consent screen.

Behavior:
  * Rate lookup is cached per-currency for the life of the process.
  * SGD passthrough returns the amount unchanged.
  * Non-SGD amounts are converted as ``amount * rate * (1 + markup)``
    and rounded to 2 decimal places with ``ROUND_HALF_UP`` so the stored
    value matches the precision the rest of the app uses.

Tests inject a stub via :func:`build_converter` patching or by passing
a fake directly into the parser.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

import httpx


class FxError(Exception):
    """Raised when an FX conversion cannot be completed."""


class FxConverter(Protocol):
    """Convert an amount in a given ISO currency to SGD."""

    def to_sgd(self, amount: Decimal, currency: str) -> Decimal: ...


class GoogleFinanceScraper:
    """Scrapes Google Finance's rendered rate for ``<CUR>-SGD``.

    The page exposes the current rate inside a ``<div class="N6SYTe">``
    wrapper that contains a span keyed by ``jsname="Pdsbrc"``. We extract
    the first decimal number after that marker. Google's consent screen
    redirects unauthenticated requests, so the scraper sends a
    ``CONSENT=YES+`` cookie to bypass that flow.

    Markup is applied on top of the mid-market rate: 1 CUR buys
    ``rate * (1 + markup)`` SGD.
    """

    TARGET = "SGD"
    ENDPOINT = "https://www.google.com/finance/quote/{currency}-SGD"
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )
    # Match the rendered rate span. The rate is wrapped in
    # <div class="N6SYTe"><span jsname="Pdsbrc" ...><span>NUMBER</span>
    _RATE_RE = re.compile(
        r'class="N6SYTe"><span jsname="Pdsbrc"[^>]*><span>([0-9][0-9,]*\.?[0-9]*)</span>',
        re.IGNORECASE,
    )

    def __init__(
        self,
        markup_pct: float = 0.005,
        timeout: float = 10.0,
        client: httpx.Client | None = None,
    ):
        if markup_pct < 0:
            raise ValueError("markup_pct must be non-negative")
        self.markup = Decimal(str(markup_pct))
        self.timeout = timeout
        # Allow tests to inject a stub client; otherwise build a fresh
        # one so connection pooling is opt-in.
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"User-Agent": self.USER_AGENT},
            cookies={"CONSENT": "YES+"},
        )
        self._cache: dict[str, Decimal] = {}

    def __del__(self):
        client = getattr(self, "_client", None)
        owns = getattr(self, "_owns_client", False)
        if owns and client is not None and not client.is_closed:
            client.close()

    def to_sgd(self, amount: Decimal, currency: str) -> Decimal:
        cur = currency.upper()
        if cur == self.TARGET:
            return amount
        rate = self._cross_rate_to_sgd(cur)
        converted = (amount * rate * (Decimal(1) + self.markup)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return converted

    def _cross_rate_to_sgd(self, currency: str) -> Decimal:
        cached = self._cache.get(currency)
        if cached is not None:
            if cached <= 0:
                raise FxError(
                    f"google_finance returned non-positive rate for {currency}"
                )
            return cached
        rate = self._lookup_rate(currency)
        if rate <= 0:
            raise FxError(
                f"google_finance returned non-positive rate for {currency}"
            )
        self._cache[currency] = rate
        return rate

    def _lookup_rate(self, currency: str) -> Decimal:
        url = self.ENDPOINT.format(currency=currency.upper())
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise FxError(f"google_finance request failed: {exc}") from exc
        m = self._RATE_RE.search(resp.text)
        if not m:
            raise FxError(
                f"google_finance returned no rate for {currency} (page layout may have changed)"
            )
        raw = m.group(1).replace(",", "")
        try:
            return Decimal(raw)
        except Exception as exc:
            raise FxError(
                f"google_finance rate was not numeric: {raw!r}"
            ) from exc


def build_converter(markup_pct: float) -> FxConverter:
    """Return the project's default FX converter.

    Currently always returns a :class:`GoogleFinanceScraper`. Kept as a
    factory so callers don't have to import the concrete class — and so
    the day we add another provider, swapping is a one-line change here.
    """
    return GoogleFinanceScraper(markup_pct=markup_pct)


__all__ = [
    "FxConverter",
    "FxError",
    "GoogleFinanceScraper",
    "build_converter",
]