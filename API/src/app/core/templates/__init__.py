"""Central template library — multi-channel, review-workflow-driven.

A standalone core module that promotes templates out of WhatsApp +
Settings into a unified library consumed by Campaigns, Email
Sequences, and (when those tracks land) the Automation Engine +
Workflows. Standard CRM pattern: HubSpot Marketing Library / Zoho
Content Library / Salesforce Marketing Cloud Content Builder.

Step 1 of `tasks/template-library/` lands the **schema + models +
schemas only** — no service, no router, no UI. The four tables here
form the polymorphic backbone every channel (WhatsApp, Email, SMS,
FB Messenger, IG Direct, Push) writes to:

- ``tbl_message_templates`` — one row per template; channel-agnostic.
  ``internal_status`` drives the org-internal review workflow
  (Step 4); ``external_status`` mirrors Meta-template approval / DLT
  registration for the channels that need it.
- ``tbl_message_template_versions`` — every edit creates a new row
  here; ``current_version`` on the parent points at the live one.
  Step 8 versions-drawer renders from these.
- ``tbl_message_template_reviews`` — append-only audit of every
  workflow action (submit / approve / reject / publish / archive)
  with reviewer + note. Used by Step 4's state machine + Step 8 UI.
- ``tbl_message_template_test_sends`` — append-only audit of every
  per-channel test send. Step 5 writes rows; Step 8 modal triggers.

Channel-specific extension tables (``tbl_whatsapp_templates`` for
Meta-specific fields, future ``tbl_sms_dlt_templates`` for TRAI
fields) link to the central row via ``external_provider_id`` and
their own reciprocal FK. This keeps the central schema
channel-agnostic while preserving the polymorphic tail.

An asset/attachments table is intentionally out of scope here —
this codebase has no ``tbl_files`` central table yet; image / PDF
attachments will be added in a future step alongside whichever
file-storage abstraction lands.
"""
