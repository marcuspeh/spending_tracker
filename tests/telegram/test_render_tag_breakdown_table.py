"""Tests for the rich-message tag breakdown table used by /today,
/week, and /month."""

from app.telegram.handlers._helpers import render_tag_breakdown_table


class TestEmpty:
    def test_returns_empty_when_no_breakdown_and_no_untagged(self):
        assert render_tag_breakdown_table({}, False, 0.0, _title="Today's spending") == ""

    def test_returns_table_when_only_untagged_flag_set(self):
        # has_untagged with an empty breakdown should still render the
        # hint row so the user knows why the table looks thin.
        html = render_tag_breakdown_table(
            {}, True, 0.0, _title="This week's spending"
        )
        assert "no tag" in html
        assert ">Total<" in html


class TestTagOrder:
    def test_emits_tags_in_default_order(self):
        # DEFAULT_TAGS order is food, coffee, transport, ..., shopping.
        # Ordering should follow the enum, not dict insertion order.
        breakdown = {"shopping": 30.0, "food": 20.0, "transport": 10.0}
        html = render_tag_breakdown_table(breakdown, False, 60.0, _title="X")
        food_idx = html.index(">Food<")
        transport_idx = html.index(">Transport<")
        shopping_idx = html.index(">Shopping<")
        assert food_idx < transport_idx < shopping_idx

    def test_unknown_tags_appended_at_bottom(self):
        # Defensive: strict /tag validation should never produce an
        # unknown tag, but if one sneaks through it lands after the
        # known ones in sorted order.
        breakdown = {"food": 5.0, "mystery": 1.0}
        html = render_tag_breakdown_table(breakdown, False, 6.0, _title="X")
        food_idx = html.index(">Food<")
        mystery_idx = html.index(">Mystery<")
        assert food_idx < mystery_idx


class TestAmountFormatting:
    def test_positive_amount_uses_plus_sign(self):
        html = render_tag_breakdown_table({"food": 12.5}, False, 12.5, _title="X")
        # The + belongs to the amount cell, not the row markup.
        assert ">+S$12.50<" in html

    def test_negative_amount_uses_minus_sign(self):
        html = render_tag_breakdown_table({"food": -4.0}, False, -4.0, _title="X")
        assert ">-S$4.00<" in html

    def test_zero_amount_has_no_sign(self):
        html = render_tag_breakdown_table({"food": 0.0}, False, 0.0, _title="X")
        assert ">S$0.00<" in html
        assert "+S$0.00" not in html
        assert "-S$0.00" not in html

    def test_negative_amount_uses_absolute_value(self):
        # Refund flows use negative amounts; the display should not
        # double the minus sign.
        html = render_tag_breakdown_table({"food": -7.50}, False, -7.50, _title="X")
        assert ">-S$7.50<" in html
        assert "--" not in html


class TestTotalRow:
    def test_total_row_always_last(self):
        breakdown = {"food": 10.0, "transport": 5.0}
        html = render_tag_breakdown_table(breakdown, False, 15.0, _title="X")
        total_row = html.rfind(">Total<")
        # The Total row should appear after every other amount row.
        assert total_row > html.index(">+S$10.00<")
        assert total_row > html.index(">+S$5.00<")
        # The closing </tr> after the Total row should be the last one
        # in the table (i.e. nothing comes after Total).
        last_close = html.rfind("</tr>")
        assert html.index("Total", total_row) < last_close

    def test_total_row_rendered_with_th_cells(self):
        html = render_tag_breakdown_table({"food": 1.0}, False, 1.0, _title="X")
        # The Total row uses <th> cells (it's a header-style row);
        # the value cell must be a <th> too so it renders bold.
        assert "<th>Total</th>" in html
        assert "<th>S$1.00</th>" in html


class TestUntaggedHint:
    def test_hint_row_appears_when_untagged_present(self):
        html = render_tag_breakdown_table(
            {"food": 5.0}, True, 5.0, _title="X"
        )
        assert "use /tag" in html

    def test_hint_row_absent_when_no_untagged(self):
        html = render_tag_breakdown_table({"food": 5.0}, False, 5.0, _title="X")
        assert "use /tag" not in html


class TestTitle:
    def test_title_in_html(self):
        html = render_tag_breakdown_table(
            {"food": 1.0}, False, 1.0, _title="This week's spending"
        )
        assert "This week's spending" in html

    def test_title_html_escaped(self):
        # Apostrophes in the title passed through the bot's user
        # input shouldn't break the markup.
        html = render_tag_breakdown_table(
            {"food": 1.0}, False, 1.0, _title="<script>alert(1)</script>"
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestTableStructure:
    def test_renders_as_native_table(self):
        html = render_tag_breakdown_table({"food": 1.0}, False, 1.0, _title="X")
        assert "<table" in html
        assert "is_bordered=\"true\"" in html
        assert "is_striped=\"true\"" in html
