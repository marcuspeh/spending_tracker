"""Tests for normalize_merchant — the cache-key + display normalizer."""

import pytest

from app.services.merchant_normalizer import normalize_merchant


class TestGrabCodeStripping:
    @pytest.mark.parametrize(
        "raw",
        [
            "Grab* 4-C8C2JJACBELYWA",
            "Grab* 7-C8C2GXK3VN5UDE",
            "Grab* A1B2C3D4E5F6G7H8",
            "Grab* X9Y8Z7W6V5U4T3S2",
            "Grab* ABCDEFGHIJKL",
            "Grab 4-C8C2JJACBELYWA",
            "Grab A1B2C3D4E5F6G7H8",
            "grab* 4-c8c2jjacbelywa",
            "  GRAB* 4-C8C2JJACBELYWA  ",
            "GrabFood",
            "GrabRide",
            "GrabMart",
            "Grab Pay",
            "grabride",
        ],
    )
    def test_grab_collapse(self, raw):
        assert normalize_merchant(raw) == "grab"


class TestPassThrough:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("STARBUCKS", "starbucks"),
            ("  Starbucks  ", "starbucks"),
            ("7-ELEVEN", "7-eleven"),
            ("FairPrice", "fairprice"),
            ("BUS/MRT", "bus/mrt"),
        ],
    )
    def test_passthrough(self, raw, expected):
        assert normalize_merchant(raw) == expected


class TestEdgeCases:
    def test_empty(self):
        assert normalize_merchant("") == ""

    def test_bare_grab_stays_grab(self):
        assert normalize_merchant("Grab") == "grab"

    def test_grab_with_only_garbage_after_asterisk_still_collapses(self):
        assert normalize_merchant("Grab* AB") == "grab"

    def test_grab_with_nonsense_token_still_collapses(self):
        assert normalize_merchant("Grab apple") == "grab"


class TestRuleRegistry:
    def teardown_method(self):
        from app.services import merchant_normalizer

        merchant_normalizer._RULES.clear()
        merchant_normalizer._RULES.extend(
            [
                merchant_normalizer._grab_rule(),
                merchant_normalizer._default_rule(),
            ]
        )

    def test_default_rules_present(self):
        from app.services.merchant_normalizer import list_rules

        assert list_rules() == ("grab_random_code", "default")

    def test_register_rule_appends(self):
        from app.services import merchant_normalizer
        from app.services.merchant_normalizer import NormalizationRule, list_rules

        def _matches(text: str) -> bool:
            return text.startswith("foo")

        merchant_normalizer.register_rule(
            NormalizationRule(name="foo_rule", matches=_matches, transform=lambda t: "FOO")
        )
        assert list_rules()[-2] == "foo_rule"
        assert "default" == list_rules()[-1]
        assert normalize_merchant("foobar") == "FOO"

    def test_register_rule_at_position(self):
        from app.services import merchant_normalizer
        from app.services.merchant_normalizer import NormalizationRule, list_rules

        merchant_normalizer.register_rule(
            NormalizationRule(
                name="first_rule",
                matches=lambda t: t == "x",
                transform=lambda t: "X",
            ),
            position=0,
        )
        assert list_rules()[0] == "first_rule"

    def test_unregister_rule(self):
        from app.services import merchant_normalizer
        from app.services.merchant_normalizer import list_rules

        assert merchant_normalizer.unregister_rule("grab_random_code") is True
        assert "grab_random_code" not in list_rules()
        assert normalize_merchant("Grab* 4-C8C2JJACBELYWA") == "grab* 4-c8c2jjacbelywa"

    def test_unregister_unknown_rule(self):
        from app.services import merchant_normalizer

        assert merchant_normalizer.unregister_rule("does_not_exist") is False