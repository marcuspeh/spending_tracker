"""Tests for the merchant blacklist helper."""

import pytest

from app.services.merchant_blacklist import BLACKLISTED_MERCHANTS, is_merchant_blacklisted


class TestIsMerchantBlacklisted:
    def test_returns_true_for_listed_merchant(self):
        assert (
            is_merchant_blacklisted("CHOCFIN PTE. LTD. - CHOCOLATE CLIENTS AC")
            is True
        )

    def test_match_is_case_insensitive(self):
        assert (
            is_merchant_blacklisted("chocfin pte. ltd. - chocolate clients ac")
            is True
        )

    def test_match_trims_whitespace(self):
        assert (
            is_merchant_blacklisted(
                "  CHOCFIN PTE. LTD. - CHOCOLATE CLIENTS AC  "
            )
            is True
        )

    def test_match_collapses_internal_whitespace(self):
        # Real parsers can emit double-spaces; the helper uses
        # normalize_merchant so the same canonicalization applies.
        assert (
            is_merchant_blacklisted(
                "CHOCFIN  PTE.   LTD.   -   CHOCOLATE  CLIENTS  AC"
            )
            is True
        )

    def test_returns_false_for_unlisted_merchant(self):
        assert is_merchant_blacklisted("Apple") is False

    def test_returns_false_for_substring_match(self):
        # Substring matching is intentionally not supported — exact
        # match only, to avoid surprise over-blocking.
        assert (
            is_merchant_blacklisted("CHOCFIN PTE. LTD.") is False
        )
        assert is_merchant_blacklisted("CHOCOLATE CLIENTS") is False

    def test_returns_false_for_empty_input(self):
        assert is_merchant_blacklisted("") is False
        assert is_merchant_blacklisted(None) is False

    def test_blacklisted_merchants_is_immutable(self):
        # Defensive guard: callers must not mutate the set at runtime.
        # If this test starts failing because someone changed the type,
        # confirm the mutation API was intentionally exposed.
        assert isinstance(BLACKLISTED_MERCHANTS, frozenset)


@pytest.mark.parametrize(
    "merchant",
    sorted(BLACKLISTED_MERCHANTS),
)
def test_every_listed_merchant_is_self_recognized(merchant):
    """Every merchant in the set should be recognized when passed back
    through :func:`is_merchant_blacklisted` (using the same
    normalization the set was built with)."""
    assert is_merchant_blacklisted(merchant) is True