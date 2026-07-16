"""Campaigns v1 Step 04 — sanitiser + plain-text deriver.

Pure Python — no DB, no fixtures. Confirms the security invariants
that keep XSS out of stored Email bodies, and that merge-tag
placeholders + inline CSS survive the round trip.
"""

from __future__ import annotations

from src.app.core.templates.sanitizer import (
    derive_plain_text,
    sanitize_email_html,
)


class TestSanitizeEmailHtml:
    def test_strips_script_tag(self):
        out = sanitize_email_html("<p>hi</p><script>alert(1)</script>")
        assert "<script>" not in out
        assert "alert" not in out
        assert "<p>hi</p>" in out

    def test_strips_iframe(self):
        out = sanitize_email_html('<iframe src="https://evil.io"></iframe><p>ok</p>')
        assert "<iframe" not in out
        assert "<p>ok</p>" in out

    def test_strips_object(self):
        out = sanitize_email_html('<object data="x.swf"></object><p>ok</p>')
        assert "<object" not in out
        assert "<p>ok</p>" in out

    def test_strips_event_handlers(self):
        out = sanitize_email_html('<a href="https://x.com" onclick="alert(1)">click</a>')
        assert "onclick" not in out
        assert 'href="https://x.com"' in out
        assert ">click</a>" in out

    def test_strips_javascript_urls(self):
        out = sanitize_email_html('<a href="javascript:alert(1)">click</a>')
        # bleach drops the disallowed href attribute; the anchor tag
        # itself can stay but must not carry the js: URL.
        assert "javascript:" not in out
        assert "alert" not in out

    def test_allows_https_and_mailto_hrefs(self):
        html = (
            '<a href="https://yourshop.com">shop</a> '
            '<a href="mailto:hi@yourshop.com">mail</a>'
        )
        out = sanitize_email_html(html)
        assert 'href="https://yourshop.com"' in out
        assert 'href="mailto:hi@yourshop.com"' in out

    def test_preserves_merge_tag_placeholders(self):
        html = "<p>Hi <strong>{{first_name}}</strong>, welcome!</p>"
        out = sanitize_email_html(html)
        assert "{{first_name}}" in out
        assert "<strong>" in out

    def test_preserves_inline_css_allowlisted_props(self):
        html = '<p style="color:#111;font-weight:bold;padding:8px;">hi</p>'
        out = sanitize_email_html(html)
        assert "color" in out
        assert "font-weight" in out
        assert "padding" in out
        assert "hi" in out

    def test_strips_disallowed_css_property(self):
        # `position:absolute` is not on the allow list — bleach should
        # drop just that property while preserving the rest of the tag.
        html = '<p style="color:#111;position:absolute;">hi</p>'
        out = sanitize_email_html(html)
        assert "position" not in out
        assert "color" in out

    def test_preserves_common_tags(self):
        html = (
            "<h1>Title</h1><p>Body</p><ul><li>A</li><li>B</li></ul>"
            "<blockquote>Q</blockquote><table><tr><td>cell</td></tr></table>"
        )
        out = sanitize_email_html(html)
        for tag in ("h1", "p", "ul", "li", "blockquote", "table", "tr", "td"):
            assert f"<{tag}>" in out or f"<{tag} " in out or f"<{tag}/" in out

    def test_empty_input_returns_empty_string(self):
        assert sanitize_email_html("") == ""
        assert sanitize_email_html(None) == ""  # type: ignore[arg-type]

    def test_strips_html_comments(self):
        out = sanitize_email_html("<!-- tracking beacon --><p>hi</p>")
        assert "<!--" not in out
        assert "tracking" not in out


class TestDerivePlainText:
    def test_strips_all_tags(self):
        out = derive_plain_text("<p>Hi <strong>world</strong>!</p>")
        assert "<p>" not in out
        assert "<strong>" not in out
        assert "Hi world!" in out

    def test_paragraph_breaks_survive(self):
        html = "<p>First para.</p><p>Second para.</p>"
        out = derive_plain_text(html)
        assert "First para." in out
        assert "Second para." in out
        # Two paragraphs get separated by at least one newline.
        assert "\n" in out

    def test_collapses_whitespace(self):
        out = derive_plain_text("<p>Hi     there</p>")
        assert "Hi there" in out
        assert "     " not in out

    def test_unescapes_common_entities(self):
        out = derive_plain_text("<p>M&amp;M &lt;3 &quot;fun&quot;</p>")
        assert "M&M" in out
        assert '"fun"' in out
        assert "<3" in out

    def test_empty_input_returns_empty_string(self):
        assert derive_plain_text("") == ""
        assert derive_plain_text(None) == ""  # type: ignore[arg-type]

    def test_merge_tags_pass_through_untouched(self):
        out = derive_plain_text("<p>Hi {{first_name}}, thanks!</p>")
        assert "{{first_name}}" in out
        assert "Hi {{first_name}}, thanks!" in out.replace("\n", " ").strip()

    def test_strips_scripts_before_extracting_text(self):
        out = derive_plain_text("<p>Hi</p><script>alert(1)</script>")
        assert "alert" not in out
        assert "Hi" in out
