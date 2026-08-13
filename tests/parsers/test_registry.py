from datetime import datetime
from decimal import Decimal

import pytest

from app.services.parsers.base import BaseParser, ParsedTransaction, ParserError
from app.services.parsers.registry import ParserRegistry


class MockParser(BaseParser):
    def __init__(self, name: str, can_parse_result: bool = True):
        self.name = name
        self._can_parse_result = can_parse_result
        self.parse_called = False

    def can_parse(self, email: dict) -> bool:
        return self._can_parse_result

    def parse(self, email: dict) -> ParsedTransaction:
        self.parse_called = True
        return ParsedTransaction(
            amount=Decimal("10.00"),
            merchant="Test",
            payment_method="TEST",
            transaction_time=datetime.now(),
        )


class TestParserRegistry:
    def _make_email(self) -> dict:
        return {"subject": "Test", "body": "test"}

    def test_register_and_get_parsers(self):
        registry = ParserRegistry()
        parser1 = MockParser("parser1")
        parser2 = MockParser("parser2")

        registry.register(parser1)
        registry.register(parser2)

        parsers = registry.get_parsers()
        assert len(parsers) == 2
        assert parsers[0].name == "parser1"
        assert parsers[1].name == "parser2"

    def test_find_parser_returns_first_match(self):
        registry = ParserRegistry()
        parser1 = MockParser("parser1", can_parse_result=True)
        parser2 = MockParser("parser2", can_parse_result=True)

        registry.register(parser1)
        registry.register(parser2)

        found = registry.find_parser(self._make_email())
        assert found is parser1

    def test_find_parser_returns_none_when_no_match(self):
        registry = ParserRegistry()
        parser = MockParser("parser", can_parse_result=False)

        registry.register(parser)

        found = registry.find_parser(self._make_email())
        assert found is None

    def test_parse_returns_transaction_when_matched(self):
        registry = ParserRegistry()
        parser = MockParser("parser", can_parse_result=True)

        registry.register(parser)

        result = registry.parse(self._make_email())
        assert result is not None
        assert result.merchant == "Test"

    def test_parse_returns_none_when_no_match(self):
        registry = ParserRegistry()
        parser = MockParser("parser", can_parse_result=False)

        registry.register(parser)

        result = registry.parse(self._make_email())
        assert result is None

    def test_selected_parser_not_try_others_on_exception(self):
        registry = ParserRegistry()

        class FailingParser(BaseParser):
            def can_parse(self, email: dict) -> bool:
                return True

            def parse(self, email: dict) -> ParsedTransaction:
                raise ParserError("Parse failed")

        parser1 = FailingParser()
        parser2 = MockParser("parser2", can_parse_result=True)

        registry.register(parser1)
        registry.register(parser2)

        email = self._make_email()
        with pytest.raises(ParserError):
            registry.parse(email)