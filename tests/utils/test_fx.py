from decimal import Decimal

import httpx
import pytest

from app.utils.fx import FxError, GoogleFinanceScraper, build_converter


def _fake_google_response(rate: str) -> str:
    """Minimal HTML stub that matches the scraper's regex."""
    return (
        '<html><body>'
        f'<div class="N6SYTe"><span jsname="Pdsbrc" class=""><span>{rate}</span></span></div>'
        '</body></html>'
    )


class TestGoogleFinanceScraperMath:
    """Pure-math checks that don't touch the network."""

    def test_sgd_passes_through_unchanged(self):
        s = GoogleFinanceScraper(markup_pct=0.005)
        assert s.to_sgd(Decimal("12.34"), "SGD") == Decimal("12.34")

    def test_lowercase_sgd_passes_through(self):
        s = GoogleFinanceScraper(markup_pct=0.005)
        assert s.to_sgd(Decimal("5.00"), "sgd") == Decimal("5.00")

    def test_markup_applied_with_rounding(self):
        s = GoogleFinanceScraper(markup_pct=0.005)
        s._cache["MYR"] = Decimal("0.30")
        # 100 * 0.30 * 1.005 = 30.15
        assert s.to_sgd(Decimal("100.00"), "MYR") == Decimal("30.15")

    def test_rounding_half_up(self):
        s = GoogleFinanceScraper(markup_pct=0.005)
        s._cache["MYR"] = Decimal("0.3015")
        # 100 * 0.3015 * 1.005 = 30.30075 → 30.30
        assert s.to_sgd(Decimal("100.00"), "MYR") == Decimal("30.30")

    def test_currency_uppercased(self):
        s = GoogleFinanceScraper(markup_pct=0.005)
        s._cache["MYR"] = Decimal("0.30")
        assert s.to_sgd(Decimal("100.00"), "myr") == Decimal("30.15")

    def test_zero_markup_returns_mid_market(self):
        s = GoogleFinanceScraper(markup_pct=0.0)
        s._cache["MYR"] = Decimal("0.30")
        assert s.to_sgd(Decimal("100.00"), "MYR") == Decimal("30.00")

    def test_negative_markup_rejected(self):
        with pytest.raises(ValueError, match="markup_pct"):
            GoogleFinanceScraper(markup_pct=-0.001)


class TestGoogleFinanceScraperHTTP:
    """Network-touching behavior, with httpx mocked via MockTransport."""

    def test_parses_rate_from_page(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_fake_google_response("0.3134"))

        client = httpx.Client(transport=httpx.MockTransport(handler))
        scraper = GoogleFinanceScraper(client=client)
        try:
            # 100 * 0.3134 * 1.005 = 31.4967 → 31.50
            assert scraper.to_sgd(Decimal("100.00"), "MYR") == Decimal("31.50")
            # Second call hits the cache, same result.
            assert scraper.to_sgd(Decimal("100"), "MYR") == Decimal("31.50")
        finally:
            scraper._client.close()

    def test_url_uses_currency_uppercase(self):
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, text=_fake_google_response("1.27"))

        client = httpx.Client(transport=httpx.MockTransport(handler))
        scraper = GoogleFinanceScraper(client=client)
        try:
            scraper.to_sgd(Decimal("10"), "usd")
        finally:
            scraper._client.close()
        assert seen == ["https://www.google.com/finance/quote/USD-SGD"]

    def test_rate_cached_after_first_lookup(self):
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(200, text=_fake_google_response("0.30"))

        client = httpx.Client(transport=httpx.MockTransport(handler))
        scraper = GoogleFinanceScraper(client=client)
        try:
            scraper.to_sgd(Decimal("100"), "MYR")
            scraper.to_sgd(Decimal("200"), "MYR")
            scraper.to_sgd(Decimal("300"), "MYR")
        finally:
            scraper._client.close()
        assert call_count["n"] == 1

    def test_missing_rate_marker_raises(self):
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(200, text="<html>no rate here</html>")
            )
        )
        scraper = GoogleFinanceScraper(client=client)
        try:
            with pytest.raises(FxError, match="google_finance returned no rate"):
                scraper.to_sgd(Decimal("100"), "MYR")
        finally:
            scraper._client.close()

    def test_http_error_raises_fx_error(self):
        client = httpx.Client(
            transport=httpx.MockTransport(lambda req: httpx.Response(503, text="down"))
        )
        scraper = GoogleFinanceScraper(client=client)
        try:
            with pytest.raises(FxError, match="google_finance request failed"):
                scraper.to_sgd(Decimal("100"), "MYR")
        finally:
            scraper._client.close()

    def test_rate_with_thousands_separator(self):
        """If Google ever renders the rate with a thousands separator,
        the scraper must strip it before parsing."""
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(200, text=_fake_google_response("1,234.56"))
            )
        )
        scraper = GoogleFinanceScraper(client=client)
        try:
            # 100 * 1234.56 * 1.005 = 124,073.28
            assert scraper.to_sgd(Decimal("100"), "USD") == Decimal("124073.28")
        finally:
            scraper._client.close()

    def test_non_positive_rate_raises(self):
        """Even a cached zero rate is rejected — guarding against weird
        provider responses that would otherwise divide by zero."""
        s = GoogleFinanceScraper(markup_pct=0.005)
        s._cache["XYZ"] = Decimal("0")
        with pytest.raises(FxError, match="non-positive"):
            s.to_sgd(Decimal("100"), "XYZ")


class TestBuildConverter:
    def test_returns_google_finance_scraper(self):
        c = build_converter(markup_pct=0.005)
        assert isinstance(c, GoogleFinanceScraper)
        assert c.markup == Decimal("0.005")