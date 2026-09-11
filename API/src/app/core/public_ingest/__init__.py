"""``core.public_ingest`` — the canonical home for public-authenticated
ingest surfaces (widget submissions, AI-widget queries, custom events).

**Facade layout, physical fold deferred.** This package establishes
the naming convention new code (custom-events, custom-events ingest)
lands into, without physically moving the existing production code
in ``core.embed`` and ``core.ai_assistants.public_*``. The physical
fold is a future cleanup track — it delivers architectural neatness
but no user-facing value, and the blast radius on production surfaces
(widget submissions + AI widget) is high, so it's deferred until it
can happen outside a feature ship.

Sub-packages:

  * ``api_keys/`` — re-exports ``ApiKey`` (formerly ``EmbedKey``) from
    ``core.embed.models``. Steps 4 fills in the hardened service layer
    here (HMAC prefilter, rotate-with-grace, live/test modes). Until
    Step 4 lands, callers can already import ``ApiKey`` from this
    namespace and it resolves to the model in ``core/embed/``.
  * ``custom_events/`` — Step 5 fills in the schema + models here;
    Step 6 fills in CRUD.
  * ``ingest/`` — Step 7 fills in the ``POST /api/v1/events/track``
    handler here (auth pipeline, payload validation, contact
    resolution, bus publish).

Shared helpers (rate-limit, idempotency, HMAC verify) live in
``api/src/app/shared/`` — Step 3 builds them there because they'll be
reused by future internal-webhook surfaces (Stripe, Twilio inbound)
too, not just public ingest.

The existing ``core/embed/`` and ``core/ai_assistants/public_*``
routers stay mounted at their current URLs and file paths. New code
imports from ``core.public_ingest.*``.
"""
