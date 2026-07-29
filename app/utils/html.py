"""HTML stripping helpers for plain-text email body extraction."""

import re

# Pre-compile the regexes for reuse; the gmail poller hits this on every
# incoming email.
_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)
_HEAD_RE = re.compile(r"<head[^>]*>.*?</head>", re.DOTALL | re.IGNORECASE)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_TAG_RE = re.compile(
    r"<\s*/?\s*(?:div|p|br|hr|li|ul|ol|tr|h[1-6])[^>]*>",
    re.IGNORECASE,
)
_WHITESPACE_RE = re.compile(r"[ \t]+")

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

    Returns a plain-text approximation of the email body. Block-level tags
    (div, p, br, hr, li, ul, ol, tr, h1-h6) are replaced with ``\\n`` so the
    original line structure is roughly preserved, suitable for parser
    consumption when no plain-text alternative exists.
    """
    if not text:
        return ""
    text = _STYLE_RE.sub("", text)
    text = _HEAD_RE.sub("", text)
    text = _COMMENT_RE.sub("", text)
    text = _BLOCK_TAG_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    for entity, replacement in _ENTITIES.items():
        text = text.replace(entity, replacement)
    text = _WHITESPACE_RE.sub(" ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()
