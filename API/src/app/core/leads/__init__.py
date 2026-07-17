"""Leads module — prospective-sale CRM entity.

Re-exports the service entry points (no FastAPI / Pydantic) and
registers `'leads'` as a pipeline-tracked card table so the engine's
`move_card` helper can UPDATE the `leads` row's `pipeline_stage`
column when the kanban drag-drops a card.

Registration happens at import time. The import chain is anchored by
`main.py` (which imports `leads.router`), so by the time the FastAPI
app starts serving the registry is populated.
"""

from src.app.core.leads.models import LeadStatus
from src.app.core.leads.service import (
    create_lead,
    delete_lead,
    get_lead,
    list_leads,
    move_stage_for_lead,
    update_lead,
)
from src.app.core.pipelines import register_pipeline_table

register_pipeline_table("tbl_leads")


__all__ = [
    "LeadStatus",
    "create_lead",
    "delete_lead",
    "get_lead",
    "list_leads",
    "move_stage_for_lead",
    "update_lead",
]
