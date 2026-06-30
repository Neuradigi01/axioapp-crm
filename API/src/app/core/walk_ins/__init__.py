"""Walk-ins module — showroom-visit tracking.

Re-exports service entry points (no FastAPI / Pydantic) so other
modules can `from src.app.core.walk_ins import quick_register, checkout`
without dragging in HTTP-layer deps. Same pattern as audit / activities
/ notifications.
"""

from src.app.core.walk_ins.models import WalkInStatus
from src.app.core.walk_ins.service import (
    checkout,
    create_walk_in,
    delete_walk_in,
    get_walk_in,
    list_walk_ins,
    quick_register,
    update_walk_in,
)

__all__ = [
    "WalkInStatus",
    "checkout",
    "create_walk_in",
    "delete_walk_in",
    "get_walk_in",
    "list_walk_ins",
    "quick_register",
    "update_walk_in",
]
