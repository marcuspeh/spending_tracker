"""Hardcoded merchant blacklist.

Merchants in this set are skipped during email ingestion — the parser
runs (so we record that the email was processed and by whom) but the
parsed transaction is never inserted and no notification is sent.

Keys are the *normalized* form (see
:func:`app.services.merchant_normalizer.normalize_merchant`): trimmed
and lowercased, with internal whitespace collapsed. Substring matching
is intentionally not supported — exact match keeps the behavior
predictable and avoids surprise over-blocking.

To add a merchant, append its normalized form to ``BLACKLISTED_MERCHANTS``
below. To suppress matching for a merchant temporarily without changing
the set, use ``merchant_blacklist.is_merchant_blacklisted(...)`` from
tests or diagnostics code.
"""

from __future__ import annotations

from app.services.merchant_normalizer import normalize_merchant


BLACKLISTED_MERCHANTS: frozenset[str] = frozenset({
    "chocfin pte. ltd. - chocolate clients ac",
})


def is_merchant_blacklisted(merchant: str | None) -> bool:
    """Return True if ``merchant`` (in any case/whitespace variant) is
    in the blacklist. Uses :func:`normalize_merchant` so the same
    canonicalization rules as the rest of the pipeline apply."""
    if not merchant:
        return False
    return normalize_merchant(merchant) in BLACKLISTED_MERCHANTS