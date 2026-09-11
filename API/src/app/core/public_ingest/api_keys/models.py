"""Re-export the ``ApiKey`` model so new code (Steps 5+) can import
from the canonical ``core.public_ingest.api_keys.models`` path.

Physical model definition lives in ``core.embed.models`` — deferred
physical fold; see ``core.public_ingest.__init__`` docstring for the
rationale.
"""

from src.app.core.embed.models import ApiKey, EmbedKey

__all__ = ["ApiKey", "EmbedKey"]
