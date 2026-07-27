"""HTML stripping helpers for plain-text email body extraction."""

import re

# Pre-compile the regexes for reuse; the gmail poller hits this on every
# incoming email.
_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)
_HEAD_RE = re.compile(r"<head[^>]*>.*?</head>", re.DOTALL | re.IGNORECASE)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

_ENTITIES = {
    "&nbsp;": " ",
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&apos;": "'",
}


def strip_html(text: str) -> str:
    """Remove HTML tags and inline CSS from text.

    Returns a single-line plain-text approximation of the email body,
    suitable for parser consumption when no plain-text alternative exists.
    """
    if not text:
        return ""
    text = _STYLE_RE.sub("", text)
    text = _HEAD_RE.sub("", text)
    text = _COMMENT_RE.sub("", text)
    text = _TAG_RE.sub(" ", text)
    for entity, replacement in _ENTITIES.items():
        text = text.replace(entity, replacement)
    return _WHITESPACE_RE.sub(" ", text).strip()
