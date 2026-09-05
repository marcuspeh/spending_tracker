"""Merchant normalizer service.

Maps a raw merchant string (e.g. "Grab* 4-C8C2JJACBELYWA") to a
canonical form used for both display and cache keying. The service is
pluggable: new rules can be added by registering a ``NormalizationRule``,
and existing rules can be reordered or removed without changing the
public :func:`normalize_merchant` API.

To add a new rule, drop a matching pattern into ``_RULES`` below (or
register one dynamically with :func:`register_rule`). The first
matching rule wins; rules are evaluated in order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class NormalizationRule:
    """A single merchant-normalization rule.

    Each rule has a ``name`` (for debugging + diagnostics), a predicate
    that returns True when the rule applies, and a transform that
    produces the canonical merchant string. The order in :data:`_RULES`
    determines precedence; the first matching rule wins.
    """

    name: str
    matches: Callable[[str], bool]
    transform: Callable[[str], str]


# ---------------------------------------------------------------------------
# Built-in rules
# ---------------------------------------------------------------------------


# DBS-card merchant strings like "Grab* 4-C8C2JJACBELYWA", "Grab
# 4-C8C2JJACBELYWA", "GrabFood", "GrabRide" — strip the random code
# (or the sub-brand suffix) so all Grab transactions share a single
# cache entry.
#
# Logic, no regex:
#   - If the merchant starts with "grab" (case-insensitive) and is
#     followed by a non-empty separator (whitespace, asterisk, or
#     another letter), collapse to "grab".
#   - Plain "grab" alone is left alone (no-op).
def _grab_rule() -> NormalizationRule:
    def _matches(text: str) -> bool:
        if not text.startswith("grab"):
            return False
        # Exact match — nothing to collapse.
        if len(text) == 4:
            return False
        next_char = text[4]
        # Anything after "grab" — a space, an asterisk, or another
        # letter (sub-brand like "GrabFood") — means we should collapse.
        return next_char in (" ", "*") or next_char.isalpha()

    return NormalizationRule(
        name="grab_random_code",
        matches=_matches,
        transform=lambda _text: "grab",
    )


# Catch-all: the caller already canonicalized whitespace+case before
# running the rule pipeline, so this rule is a structural no-op that
# guarantees every input matches exactly one rule.
def _default_rule() -> NormalizationRule:
    return NormalizationRule(
        name="default",
        matches=lambda _text: True,
        transform=lambda text: text,
    )


# Rules in priority order. The first match wins; the default rule at
# the end always matches so the output is always normalized.
_RULES: list[NormalizationRule] = [
    _grab_rule(),
    _default_rule(),
]


def register_rule(rule: NormalizationRule, *, position: int | None = None) -> None:
    """Add or replace a normalization rule.

    Args:
        rule: the new rule to add.
        position: 0-based index for the new rule. ``None`` (default)
            appends *before* the default rule — the default rule is
            always pinned at the end so a new rule never sits behind it.

    Notes:
        The default rule matches everything and is always at the end.
        To put a rule in front of the default, pass ``position=0`` or
        any other position.
    """
    if position is None:
        # Insert before the default rule (which is always last).
        default_index = len(_RULES) - 1 if _RULES else 0
        _RULES.insert(default_index, rule)
    else:
        _RULES.insert(position, rule)


def unregister_rule(name: str) -> bool:
    """Remove a rule by name. Returns True if a rule was removed."""
    for i, rule in enumerate(_RULES):
        if rule.name == name:
            _RULES.pop(i)
            return True
    return False


def list_rules() -> tuple[str, ...]:
    """Return the names of all registered rules in evaluation order."""
    return tuple(r.name for r in _RULES)


def normalize_merchant(merchant: str) -> str:
    """Normalize a merchant string for display + cache-key use.

    Lowercases and trims the input, then applies the first matching
    rule in :data:`_RULES`. Returns ``""`` for an empty / None-ish input.

    Add new behavior by calling :func:`register_rule` with a
    :class:`NormalizationRule`. The first matching rule wins.
    """
    if not merchant:
        return ""

    # Lowercase + collapse whitespace up front so every rule sees a
    # canonical input. Use str.split() instead of regex — no patterns
    # to maintain.
    text = " ".join(merchant.strip().lower().split())
    for rule in _RULES:
        if rule.matches(text):
            text = rule.transform(text)
            break
    return text
