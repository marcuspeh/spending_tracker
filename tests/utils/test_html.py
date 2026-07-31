from app.utils.html import strip_html


class TestStripHtml:
    def test_empty_input(self):
        assert strip_html("") == ""

    def test_none_input(self):
        assert strip_html(None) == ""

    def test_plain_text_unchanged(self):
        assert strip_html("Hello world") == "Hello world"

    def test_strips_style_blocks(self):
        html = "<style>p { color: red; }</style><p>Hello</p>"
        assert strip_html(html) == "Hello"

    def test_strips_head_blocks(self):
        html = "<head><meta charset='utf-8'><title>X</title></head><body>Body</body>"
        assert "meta" not in strip_html(html)
        assert "Body" in strip_html(html)

    def test_strips_html_comments(self):
        html = "Before <!-- a comment --> After"
        assert strip_html(html) == "Before After"

    def test_strips_simple_tags(self):
        html = "<p>Hello <b>world</b></p>"
        assert strip_html(html) == "Hello world"

    def test_decodes_entities(self):
        assert strip_html("Hello&nbsp;World") == "Hello World"
        assert strip_html("AT&amp;T") == "AT&T"
        assert strip_html("&lt;tag&gt;") == "<tag>"
        assert strip_html("&quot;quoted&quot;") == '"quoted"'

    def test_collapses_whitespace(self):
        html = "<p>Hello</p>\n\n<p>World</p>"
        assert strip_html(html) == "Hello World"

    def test_handles_dbs_style_email(self):
        """The realistic case from the poller — full DBS card alert HTML."""
        html = (
            "<!DOCTYPE html><html><head><style>body { margin: 0 }</style></head>"
            "<body><table><tr><td>Card Transaction Alert</td></tr>"
            "<tr><td>Date &amp; Time: 16 JUL 12:39 (SGT)<br>"
            "Amount: SGD2.15<br>From: DBS card ending 2453<br>"
            "To: APPLE.COM/BILL</td></tr></table></body></html>"
        )
        result = strip_html(html)
        assert "Card Transaction Alert" in result
        assert "SGD2.15" in result
        assert "APPLE.COM/BILL" in result
        assert "margin" not in result  # CSS stripped

    def test_no_repr_crash_on_long_input(self):
        """Sanity check that long inputs don't cause pathological backtracking."""
        # 5KB of style tags — would ReDoS on a vulnerable regex
        html = "<style>" + "p { color: red; }" * 200 + "</style>" + "<p>x</p>"
        result = strip_html(html)
        assert "x" in result

    def test_remove_extra_newlines(self):
        html = "<p>Hello\n\n\n\nWorld</p>"
        assert strip_html(html) == "Hello\nWorld"