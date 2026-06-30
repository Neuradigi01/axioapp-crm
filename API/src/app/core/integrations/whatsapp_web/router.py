"""HTTP routes for the WhatsApp Web (unofficial / Baileys) integration.

**Step 4 status:** scaffold only — empty ``APIRouter`` is exported so
``core/integrations/router.py`` can ``include_router`` it now, without
the rest of the system needing a follow-up edit when Step 5 adds the
first endpoints.

Step 5 will mount on this router::

  POST   /api/v1/integrations/whatsapp-web/connect            — start pairing
  POST   /api/v1/integrations/whatsapp-web/disconnect         — destroy session
  GET    /api/v1/integrations/whatsapp-web/status             — projection
  GET    /api/v1/integrations/whatsapp-web/qr/{id}/stream     — SSE QR feed (Step 6)
  POST   /api/v1/integrations/whatsapp-web/events             — sidecar inbound (Step 6)
"""
from __future__ import annotations

from fastapi import APIRouter


router = APIRouter(
    prefix="/whatsapp-web",
    tags=["Integrations · WhatsApp Web"],
)
