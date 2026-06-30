"""Gmail provider sub-package.

Importing this module registers the `GmailProvider` instance into
the OAuth provider registry from `core.email.oauth`. Step 1's
`service.refresh_if_expired` dispatches to this provider whenever an
account row has `provider='gmail'`. Without this side-effect import,
the lookup would return None and refresh attempts would fail.

The registration runs once per process. `oauth.register_provider` is
idempotent — re-registering the same name overwrites silently (used
in tests to swap in mocks).
"""

from src.app.core.email.gmail.oauth import GmailProvider
from src.app.core.email.oauth import register_provider

register_provider(GmailProvider())
