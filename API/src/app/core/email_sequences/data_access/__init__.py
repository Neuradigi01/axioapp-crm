"""Data-access layer for the email-sequences module.

Per-module ``data_access/`` folder per the project convention. Pure
query helpers, no transactions, no audit. Leaf — never imports a
service.py.

Sub-modules:

  - :mod:`templates` — post-Step-10 lookups that validate central
    ``tbl_message_templates`` rows can back a sequence step.
"""
from src.app.core.email_sequences.data_access.templates import (
    list_valid_email_template_ids,
)


__all__ = ["list_valid_email_template_ids"]
