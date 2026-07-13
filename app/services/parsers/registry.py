from typing import Any

from app.services.parsers.base import BaseParser, ParsedTransaction


class ParserRegistry:
    """Registry of email parsers that selects the first matching parser."""

    def __init__(self):
        self._parsers: list[BaseParser] = []

    def register(self, parser: BaseParser) -> None:
        """Register a parser."""
        self._parsers.append(parser)

    def get_parsers(self) -> list[BaseParser]:
        """Get all registered parsers."""
        return self._parsers.copy()

    def find_parser(self, email: dict[str, Any]) -> BaseParser | None:
        """Find the first parser that can handle the email.

        Args:
            email: Email dict with 'subject', 'body', 'from', etc.

        Returns:
            The first matching parser or None if no parser can handle the email.
        """
        for parser in self._parsers:
            if parser.can_parse(email):
                return parser
        return None

    def parse(self, email: dict[str, Any]) -> ParsedTransaction | None:
        """Parse the email using the first matching parser.

        Args:
            email: Email dict with 'subject', 'body', 'from', etc.

        Returns:
            ParsedTransaction if a parser matches, None otherwise.
        """
        parser = self.find_parser(email)
        if parser:
            return parser.parse(email)
        return None
