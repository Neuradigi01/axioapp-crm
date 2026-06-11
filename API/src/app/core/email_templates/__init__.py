"""core.email_templates — org-scoped library of reusable email templates.

A template carries a name, subject, HTML body, plain-text body
(auto-derived), and the set of variable paths it uses. Step 5's
adapter calls `service.render(template, context)` to materialise
a ready-to-send subject + body pair from a saved template + a
build-time context (contact + optional lead + sender + org).

Variable engine lives in `core.email.variables` — shared with any
future surface that wants safe `{{ contact.field }}` substitution
(e.g. Step 7's sequence pre-flight preview).
"""
