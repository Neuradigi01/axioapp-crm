"""Email quarantine + filter rules — Track 5 of the email-platform track.

Two tables:

  * ``tbl_email_quarantine`` — held-mail rows for suspicious inbound.
    Release routes back through ``_persist_inbound_email``; discard
    deletes the row + on-disk payload. Auto-purged after 30 d.

  * ``tbl_email_filter_rules`` — per-org allow / block precedence
    ladder (address > contact-flag > domain; allow beats block).
"""
