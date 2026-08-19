"""HTTP helpers shared across features.

Reusable, security-hardened HTTP surfaces that would otherwise be
re-invented per feature. First entry is
:mod:`shared.http.safe_fetch` — an SSRF-defence fetcher for URL-
based knowledge ingest (``tasks/ai-assistants`` Step 10) that
DNS-resolves every hop and refuses RFC1918 / link-local / loopback
targets.
"""
