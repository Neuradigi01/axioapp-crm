"""Output sanitiser for public embed replies
(``tasks/ai-assistants`` Step 9; Attacker review H8).

Strips URLs and email addresses from an assistant's reply whose
host / domain is not on the assistant's ``allowed_domains`` list.
Defence in depth against an insider who edits ``instructions`` to
inject an exfiltration URL: even if the LLM emits
``http://attacker.com/collect?data=…`` into the reply, the
sanitiser removes it before the widget renders (public embeds
only — operator preview shows the raw reply).

Not perfect (RFC 3986 URL matching is a known-hard problem), but
combined with the structured-JSON-envelope prompt injection
defence in ``runtime.py``, it raises the bar significantly. See
the step's Risks note.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# URL matcher — plain HTTP(S) + ``www.`` bare-domain URLs. Intent
# is to match anything a browser would auto-linkify; edge cases
# (unicode IDNA, protocol-relative ``//example.com``) fall through
# but are rare in LLM output.
_URL_RE = re.compile(
    r"""(?xi)
    \b
    (?:https?://|www\.)              # scheme or www.
    [^\s<>()\[\]{}"']+                # host + path (greedy, no whitespace/brackets)
    """,
)

# Simple RFC 5322-ish email matcher — good enough for stripping.
_EMAIL_RE = re.compile(
    r"""(?xi)
    \b
    [A-Z0-9._%+\-]+@                  # local part
    ([A-Z0-9.\-]+\.[A-Z]{2,})         # domain
    \b
    """,
)


def _normalise_domain(raw: str) -> str:
    """Lower-case + strip ``www.`` so ``Example.com`` == ``www.example.com``."""
    d = raw.strip().lower().lstrip(".")
    if d.startswith("www."):
        d = d[4:]
    return d


def _extract_url_host(url: str) -> str:
    """Return the host from a URL string, defensively. Returns empty
    string on parse failure so the caller treats it as off-allow-list."""
    candidate = url
    if candidate.lower().startswith("www."):
        candidate = "http://" + candidate
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return ""
    return _normalise_domain(parsed.hostname or "")


def _extract_email_domain(email: str) -> str:
    _, _, domain = email.rpartition("@")
    return _normalise_domain(domain)


def _is_on_allow_list(domain: str, allow_list: frozenset[str]) -> bool:
    """Match against ``allow_list`` with a subdomain check —
    ``support.example.com`` matches an allow-list entry
    ``example.com``. Empty allow-list means "strip everything"
    (the default for a fresh assistant)."""
    if not domain:
        return False
    if domain in allow_list:
        return True
    # Suffix match: allow-list ``example.com`` matches
    # ``support.example.com`` but not ``example.com.attacker.io``.
    return any(domain.endswith(f".{allowed}") for allowed in allow_list)


def sanitize_output(text: str, allowed_domains: list[str]) -> str:
    """Return ``text`` with off-allow-list URLs + emails removed.

    Substitutes each match with ``[removed link]`` / ``[removed
    email]`` respectively so the sanitised gap is visible to the
    end-user rather than silently absent. Callers should surface a
    small banner ("Some links removed for safety") in the widget on
    a first sanitisation event; not part of this pure function.
    """
    allow_set: frozenset[str] = frozenset(_normalise_domain(d) for d in allowed_domains if d)

    def _url_sub(match: re.Match[str]) -> str:
        url = match.group(0).rstrip(".,;:)]}\"'")
        host = _extract_url_host(url)
        if _is_on_allow_list(host, allow_set):
            return url
        return "[removed link]"

    def _email_sub(match: re.Match[str]) -> str:
        email = match.group(0)
        domain = _extract_email_domain(email)
        if _is_on_allow_list(domain, allow_set):
            return email
        return "[removed email]"

    stripped = _URL_RE.sub(_url_sub, text)
    stripped = _EMAIL_RE.sub(_email_sub, stripped)
    return stripped


__all__ = ["sanitize_output"]
