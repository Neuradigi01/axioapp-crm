"""Pure-Python tests for :func:`sanitize_output`."""

from __future__ import annotations

from src.app.core.ai_assistants.output_sanitizer import sanitize_output


def test_url_off_allow_list_stripped() -> None:
    out = sanitize_output(
        "Visit https://attacker.com/collect?data=x for more info",
        allowed_domains=["example.com"],
    )
    assert "attacker.com" not in out
    assert "[removed link]" in out
    assert "Visit" in out and "for more info" in out


def test_url_on_allow_list_preserved() -> None:
    out = sanitize_output(
        "Read https://example.com/docs for guidance",
        allowed_domains=["example.com"],
    )
    assert "https://example.com/docs" in out


def test_subdomain_match_of_allow_list() -> None:
    out = sanitize_output(
        "Reach https://support.example.com for help",
        allowed_domains=["example.com"],
    )
    assert "support.example.com" in out


def test_suffix_confusion_not_matched() -> None:
    """A canonical Attacker H8 case: an allow-list of ``example.com``
    must NOT accept ``example.com.attacker.io``."""
    out = sanitize_output(
        "Actually go to https://example.com.attacker.io/steal instead",
        allowed_domains=["example.com"],
    )
    assert "attacker.io" not in out
    assert "[removed link]" in out


def test_email_off_allow_list_stripped() -> None:
    out = sanitize_output(
        "Contact leaker@attacker.com to escalate",
        allowed_domains=["example.com"],
    )
    assert "attacker.com" not in out
    assert "[removed email]" in out


def test_email_on_allow_list_preserved() -> None:
    out = sanitize_output(
        "Contact support@example.com",
        allowed_domains=["example.com"],
    )
    assert "support@example.com" in out


def test_empty_allow_list_strips_all_urls_and_emails() -> None:
    """No allow-list = strict — every URL / email removed."""
    out = sanitize_output(
        "See https://any.com or email user@any.com",
        allowed_domains=[],
    )
    assert "any.com" not in out
    assert "[removed link]" in out
    assert "[removed email]" in out


def test_case_insensitive_allow_list() -> None:
    out = sanitize_output(
        "See https://EXAMPLE.com/docs",
        allowed_domains=["Example.COM"],
    )
    assert "EXAMPLE.com" in out


def test_www_prefix_normalised() -> None:
    """Allow-list entry ``example.com`` must match ``www.example.com``."""
    out = sanitize_output(
        "Try https://www.example.com/home",
        allowed_domains=["example.com"],
    )
    assert "www.example.com" in out


def test_plain_text_unaffected() -> None:
    text = "This message has no URLs or emails at all."
    assert sanitize_output(text, allowed_domains=["example.com"]) == text
