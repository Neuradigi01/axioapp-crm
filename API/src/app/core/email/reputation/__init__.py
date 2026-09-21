"""Email reputation + warmup module.

Two surfaces:

  * :mod:`.models` — persistent state in
    ``tbl_organization_email_reputation`` (warmup stage, block-until,
    daily counter).
  * :mod:`.counters` — 24h rolling event counters in Redis (delivered,
    bounced, complained per org × envelope × hour bucket).

Steps 3–7 build the events webhook, evaluators, send-gate integration,
and dashboard on top.
"""
