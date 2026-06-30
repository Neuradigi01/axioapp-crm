"""Service layer for the WhatsApp Web integration.

**Step 4 status:** scaffold only. The connect / disconnect / status
flows that wire FastAPI to the Node sidecar land in Step 5
(``tasks/whatsapp-unofficial/step-05-fastapi-connect-and-sidecar-client.md``).
The inbound events handler lands in Step 6 and the
``ChannelAdapter`` integration in Step 7.

Per the layered-architecture rule (see ``API/tests/
test_layered_architecture_convention.py``) this is the only layer
that should call ``db.commit / db.refresh / db.flush`` for this
module — those calls will be added alongside the Step-5 flows.
"""
from __future__ import annotations


__all__: list[str] = []
