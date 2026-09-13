"""API-keys sub-package under ``core.public_ingest``.

Step 4 fills in ``service.py`` (HMAC-of-full-key prefilter defeating
Argon2id DoS, rotate-with-grace 24h flow, ``pk_live_*``/``pk_test_*``
mode enforcement, sequential-rotation 409 guard) + ``router.py``
(Owner-only CRUD + reveal endpoint) + ``data_access.py``.

Until Step 4 lands, this package re-exports the ``ApiKey`` model from
``core.embed.models`` so new callers can already write
``from src.app.core.public_ingest.api_keys.models import ApiKey`` — the
import resolves to the same class regardless of which path it's
imported from (Python module identity is by object, not path).
"""

from src.app.core.public_ingest.api_keys.models import ApiKey, EmbedKey

__all__ = ["ApiKey", "EmbedKey"]
