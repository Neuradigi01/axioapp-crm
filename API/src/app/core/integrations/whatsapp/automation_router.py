"""HTTP routes for the keyword-rule automation surface
(whatsapp-platform-upgrade Step 17).

  GET    /api/v1/integrations/whatsapp/keyword-rules
  POST   /api/v1/integrations/whatsapp/keyword-rules
  GET    /api/v1/integrations/whatsapp/keyword-rules/{id}
  PATCH  /api/v1/integrations/whatsapp/keyword-rules/{id}
  DELETE /api/v1/integrations/whatsapp/keyword-rules/{id}
  POST   /api/v1/integrations/whatsapp/keyword-rules/reorder
  POST   /api/v1/integrations/whatsapp/keyword-rules/test

Permission: ``whatsapp.automation.manage`` (Owner / Admin by default
via role templates).
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.auth.dependencies import require_permissions
from src.app.core.integrations.whatsapp.keyword_engine import evaluate_rules
from src.app.core.integrations.whatsapp.models import (
    AssignmentStrategy,
    KeywordActionType,
    KeywordMatchType,
    WhatsAppAssignmentRule,
    WhatsAppKeywordAction,
    WhatsAppKeywordRule,
)
from src.app.core.integrations.whatsapp.connect import get_active_config
from src.app.core.integrations.whatsapp.schemas import (
    AISettingsPatch,
    AISettingsRead,
    AssignmentRuleRead,
    AssignmentRuleReorder,
    AssignmentRuleUpsert,
    KeywordActionRead,
    KeywordRuleRead,
    KeywordRuleReorder,
    KeywordRuleUpsert,
    RuleTestRequest,
    RuleTestResponse,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(
    prefix="/whatsapp/keyword-rules",
    tags=["Integrations · WhatsApp · Automation"],
)


async def _project(
    session: AsyncSession, rule: WhatsAppKeywordRule
) -> KeywordRuleRead:
    """Hydrate `actions[]` onto the rule projection. Done in a single
    helper so the CRUD endpoints stay one-liners."""
    actions = (
        await session.execute(
            select(WhatsAppKeywordAction)
            .where(WhatsAppKeywordAction.rule_id == rule.id)
            .order_by(
                WhatsAppKeywordAction.position.asc(),
                WhatsAppKeywordAction.created_at.asc(),
            )
        )
    ).scalars().all()
    return KeywordRuleRead.model_validate(
        {
            "id": rule.id,
            "name": rule.name,
            "keywords": list(rule.keywords or []),
            "match_type": rule.match_type.value,
            "enabled": rule.enabled,
            "priority": rule.priority,
            "created_by_user_id": rule.created_by_user_id,
            "created_at": rule.created_at,
            "updated_at": rule.updated_at,
            "actions": [
                KeywordActionRead(
                    id=a.id,
                    action_type=a.action_type.value,
                    action_config=a.action_config or {},
                    position=a.position,
                )
                for a in actions
            ],
        }
    )


async def _get_or_404(
    session: AsyncSession, rule_id: uuid.UUID
) -> WhatsAppKeywordRule:
    row = (
        await session.execute(
            select(WhatsAppKeywordRule).where(
                WhatsAppKeywordRule.id == rule_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Keyword rule not found.",
        )
    return row


@router.get("", response_model=list[KeywordRuleRead])
async def list_rules_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(
        require_permissions("whatsapp.automation.manage")
    ),
) -> list[KeywordRuleRead]:
    rules = (
        await db.execute(
            select(WhatsAppKeywordRule).order_by(
                WhatsAppKeywordRule.priority.asc(),
                WhatsAppKeywordRule.created_at.asc(),
            )
        )
    ).scalars().all()
    return [await _project(db, r) for r in rules]


@router.post(
    "",
    response_model=KeywordRuleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_rule_endpoint(
    payload: KeywordRuleUpsert,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_permissions("whatsapp.automation.manage")
    ),
) -> KeywordRuleRead:
    rule = WhatsAppKeywordRule(
        org_id=user.org_id,
        name=payload.name,
        keywords=list(payload.keywords),
        match_type=KeywordMatchType(payload.match_type),
        enabled=payload.enabled,
        priority=payload.priority,
        created_by_user_id=user.legacy_uuid,
    )
    db.add(rule)
    await db.flush()
    for idx, action in enumerate(payload.actions):
        db.add(
            WhatsAppKeywordAction(
                org_id=user.org_id,
                rule_id=rule.id,
                action_type=KeywordActionType(action.action_type),
                action_config=action.action_config or {},
                position=action.position if action.position else idx,
            )
        )
    await db.commit()
    await db.refresh(rule)
    await audit.log(
        "integration.whatsapp.keyword_rule_created",
        entity_type="whatsapp_keyword_rule",
        entity_id=rule.id,
        user_id=user.legacy_uuid,
        after={"name": rule.name, "match_type": rule.match_type.value},
    )
    return await _project(db, rule)


@router.get("/{rule_id}", response_model=KeywordRuleRead)
async def get_rule_endpoint(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(
        require_permissions("whatsapp.automation.manage")
    ),
) -> KeywordRuleRead:
    rule = await _get_or_404(db, rule_id)
    return await _project(db, rule)


@router.patch("/{rule_id}", response_model=KeywordRuleRead)
async def update_rule_endpoint(
    rule_id: uuid.UUID,
    payload: KeywordRuleUpsert,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_permissions("whatsapp.automation.manage")
    ),
) -> KeywordRuleRead:
    """Full rewrite — replaces the rule's actions atomically. Partial
    edits could surgically diff the actions list but the rule editor
    posts the full state on save so the cleanest semantics is "swap
    in the new shape"."""
    rule = await _get_or_404(db, rule_id)
    before = {
        "name": rule.name,
        "match_type": rule.match_type.value,
        "enabled": rule.enabled,
        "priority": rule.priority,
        "keywords": list(rule.keywords or []),
    }
    rule.name = payload.name
    rule.keywords = list(payload.keywords)
    rule.match_type = KeywordMatchType(payload.match_type)
    rule.enabled = payload.enabled
    rule.priority = payload.priority
    # Replace actions in place — delete old, insert new.
    await db.execute(
        delete(WhatsAppKeywordAction).where(
            WhatsAppKeywordAction.rule_id == rule.id
        )
    )
    for idx, action in enumerate(payload.actions):
        db.add(
            WhatsAppKeywordAction(
                org_id=user.org_id,
                rule_id=rule.id,
                action_type=KeywordActionType(action.action_type),
                action_config=action.action_config or {},
                position=action.position if action.position else idx,
            )
        )
    await db.commit()
    await db.refresh(rule)
    await audit.log(
        "integration.whatsapp.keyword_rule_updated",
        entity_type="whatsapp_keyword_rule",
        entity_id=rule.id,
        user_id=user.legacy_uuid,
        before=before,
        after={
            "name": rule.name,
            "match_type": rule.match_type.value,
            "enabled": rule.enabled,
            "priority": rule.priority,
            "keywords": list(rule.keywords or []),
        },
    )
    return await _project(db, rule)


@router.delete(
    "/{rule_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_rule_endpoint(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_permissions("whatsapp.automation.manage")
    ),
) -> Response:
    rule = await _get_or_404(db, rule_id)
    snapshot = {"name": rule.name, "keywords": list(rule.keywords or [])}
    await db.delete(rule)
    await db.commit()
    await audit.log(
        "integration.whatsapp.keyword_rule_deleted",
        entity_type="whatsapp_keyword_rule",
        entity_id=rule_id,
        user_id=user.legacy_uuid,
        before=snapshot,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/reorder", response_model=list[KeywordRuleRead])
async def reorder_rules_endpoint(
    payload: KeywordRuleReorder,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_permissions("whatsapp.automation.manage")
    ),
) -> list[KeywordRuleRead]:
    """Reassigns `priority` based on the new id ordering — first id =
    priority 10, second = 20, etc. Steps of 10 leave room for the
    operator to manually drop a rule between two without a full
    reorder pass."""
    rules = (
        await db.execute(
            select(WhatsAppKeywordRule).where(
                WhatsAppKeywordRule.id.in_(payload.rule_ids)
            )
        )
    ).scalars().all()
    by_id = {r.id: r for r in rules}
    if len(by_id) != len(payload.rule_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more rule ids in the reorder list do not exist.",
        )
    for idx, rid in enumerate(payload.rule_ids):
        by_id[rid].priority = (idx + 1) * 10
    await db.commit()
    await audit.log(
        "integration.whatsapp.keyword_rules_reordered",
        entity_type="whatsapp_keyword_rule",
        entity_id=None,
        user_id=user.legacy_uuid,
        after={"rule_ids": [str(rid) for rid in payload.rule_ids]},
    )
    refreshed = (
        await db.execute(
            select(WhatsAppKeywordRule).order_by(
                WhatsAppKeywordRule.priority.asc(),
                WhatsAppKeywordRule.created_at.asc(),
            )
        )
    ).scalars().all()
    return [await _project(db, r) for r in refreshed]


@router.post("/test", response_model=RuleTestResponse)
async def test_rule_endpoint(
    payload: RuleTestRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(
        require_permissions("whatsapp.automation.manage")
    ),
) -> RuleTestResponse:
    """Dry-run — evaluate `text` against the active rules + return
    the first match's id + projected action list. Performs no
    sends / tags / assigns."""
    result = await evaluate_rules(db, text=payload.text)
    if result.rule is None:
        return RuleTestResponse()
    return RuleTestResponse(
        matched_rule_id=result.rule.id,
        matched_rule_name=result.rule.name,
        actions=[
            KeywordActionRead(
                id=a.id,
                action_type=a.action_type.value,
                action_config=a.action_config or {},
                position=a.position,
            )
            for a in result.actions
        ],
    )


# --- Assignment rules (whatsapp-platform-upgrade Step 18) --------------


assignment_router = APIRouter(
    prefix="/whatsapp/assignment-rules",
    tags=["Integrations · WhatsApp · Automation"],
)


async def _assignment_get_or_404(
    session: AsyncSession, rule_id: uuid.UUID
) -> WhatsAppAssignmentRule:
    row = (
        await session.execute(
            select(WhatsAppAssignmentRule).where(
                WhatsAppAssignmentRule.id == rule_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment rule not found.",
        )
    return row


@assignment_router.get("", response_model=list[AssignmentRuleRead])
async def list_assignment_rules_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(
        require_permissions("whatsapp.automation.manage")
    ),
) -> list[AssignmentRuleRead]:
    rules = (
        await db.execute(
            select(WhatsAppAssignmentRule).order_by(
                WhatsAppAssignmentRule.priority.asc(),
                WhatsAppAssignmentRule.created_at.asc(),
            )
        )
    ).scalars().all()
    return [AssignmentRuleRead.model_validate(r) for r in rules]


@assignment_router.post(
    "",
    response_model=AssignmentRuleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_assignment_rule_endpoint(
    payload: AssignmentRuleUpsert,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_permissions("whatsapp.automation.manage")
    ),
) -> AssignmentRuleRead:
    rule = WhatsAppAssignmentRule(
        org_id=user.org_id,
        name=payload.name,
        strategy=AssignmentStrategy(payload.strategy),
        config=payload.config,
        enabled=payload.enabled,
        priority=payload.priority,
        skip_outside_hours=payload.skip_outside_hours,
        created_by_user_id=user.legacy_uuid,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    await audit.log(
        "integration.whatsapp.assignment_rule_created",
        entity_type="whatsapp_assignment_rule",
        entity_id=rule.id,
        user_id=user.legacy_uuid,
        after={"name": rule.name, "strategy": rule.strategy.value},
    )
    return AssignmentRuleRead.model_validate(rule)


@assignment_router.patch(
    "/{rule_id}", response_model=AssignmentRuleRead
)
async def update_assignment_rule_endpoint(
    rule_id: uuid.UUID,
    payload: AssignmentRuleUpsert,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_permissions("whatsapp.automation.manage")
    ),
) -> AssignmentRuleRead:
    rule = await _assignment_get_or_404(db, rule_id)
    before = {
        "name": rule.name,
        "strategy": rule.strategy.value,
        "enabled": rule.enabled,
        "priority": rule.priority,
        "skip_outside_hours": rule.skip_outside_hours,
    }
    rule.name = payload.name
    rule.strategy = AssignmentStrategy(payload.strategy)
    rule.config = payload.config
    rule.enabled = payload.enabled
    rule.priority = payload.priority
    rule.skip_outside_hours = payload.skip_outside_hours
    await db.commit()
    await db.refresh(rule)
    await audit.log(
        "integration.whatsapp.assignment_rule_updated",
        entity_type="whatsapp_assignment_rule",
        entity_id=rule.id,
        user_id=user.legacy_uuid,
        before=before,
        after={
            "name": rule.name,
            "strategy": rule.strategy.value,
            "enabled": rule.enabled,
            "priority": rule.priority,
            "skip_outside_hours": rule.skip_outside_hours,
        },
    )
    return AssignmentRuleRead.model_validate(rule)


@assignment_router.delete(
    "/{rule_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_assignment_rule_endpoint(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_permissions("whatsapp.automation.manage")
    ),
) -> Response:
    rule = await _assignment_get_or_404(db, rule_id)
    snapshot = {"name": rule.name, "strategy": rule.strategy.value}
    await db.delete(rule)
    await db.commit()
    await audit.log(
        "integration.whatsapp.assignment_rule_deleted",
        entity_type="whatsapp_assignment_rule",
        entity_id=rule_id,
        user_id=user.legacy_uuid,
        before=snapshot,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@assignment_router.post(
    "/reorder", response_model=list[AssignmentRuleRead]
)
async def reorder_assignment_rules_endpoint(
    payload: AssignmentRuleReorder,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_permissions("whatsapp.automation.manage")
    ),
) -> list[AssignmentRuleRead]:
    rules = (
        await db.execute(
            select(WhatsAppAssignmentRule).where(
                WhatsAppAssignmentRule.id.in_(payload.rule_ids)
            )
        )
    ).scalars().all()
    by_id = {r.id: r for r in rules}
    if len(by_id) != len(payload.rule_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more rule ids do not exist.",
        )
    for idx, rid in enumerate(payload.rule_ids):
        by_id[rid].priority = (idx + 1) * 10
    await db.commit()
    await audit.log(
        "integration.whatsapp.assignment_rules_reordered",
        entity_type="whatsapp_assignment_rule",
        entity_id=None,
        user_id=user.legacy_uuid,
        after={"rule_ids": [str(rid) for rid in payload.rule_ids]},
    )
    refreshed = (
        await db.execute(
            select(WhatsAppAssignmentRule).order_by(
                WhatsAppAssignmentRule.priority.asc(),
                WhatsAppAssignmentRule.created_at.asc(),
            )
        )
    ).scalars().all()
    return [AssignmentRuleRead.model_validate(r) for r in refreshed]


# --- AI settings (whatsapp-platform-upgrade Step 19) --------------------


ai_settings_router = APIRouter(
    prefix="/whatsapp/ai",
    tags=["Integrations · WhatsApp · Automation"],
)


@ai_settings_router.get(
    "/settings", response_model=AISettingsRead
)
async def get_ai_settings_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(
        require_permissions("whatsapp.automation.manage")
    ),
) -> AISettingsRead:
    """Read the org-wide AI knobs (default-enable, confidence
    threshold, handover keywords, system prompt). 409 when the org
    hasn't connected WhatsApp — the rest of the page handles that
    branch already."""
    bundle = await get_active_config(db)
    if bundle is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="WhatsApp is not connected for this org.",
        )
    _, config = bundle
    return AISettingsRead(
        ai_handling_default_enabled=config.ai_handling_default_enabled,
        ai_confidence_threshold=float(config.ai_confidence_threshold),
        ai_handover_keywords=list(config.ai_handover_keywords or []),
        ai_system_prompt=config.ai_system_prompt,
    )


@ai_settings_router.patch(
    "/settings", response_model=AISettingsRead
)
async def patch_ai_settings_endpoint(
    payload: AISettingsPatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_permissions("whatsapp.automation.manage")
    ),
) -> AISettingsRead:
    bundle = await get_active_config(db)
    if bundle is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="WhatsApp is not connected for this org.",
        )
    _, config = bundle

    patch_dict = payload.model_dump(exclude_unset=True, mode="python")
    before = {
        "ai_handling_default_enabled": config.ai_handling_default_enabled,
        "ai_confidence_threshold": float(config.ai_confidence_threshold),
        "ai_handover_keywords": list(config.ai_handover_keywords or []),
        "ai_system_prompt": config.ai_system_prompt,
    }

    if "ai_handling_default_enabled" in patch_dict:
        config.ai_handling_default_enabled = bool(
            patch_dict["ai_handling_default_enabled"]
        )
    if "ai_confidence_threshold" in patch_dict:
        config.ai_confidence_threshold = float(
            patch_dict["ai_confidence_threshold"]
        )
    if "ai_handover_keywords" in patch_dict:
        # Strip + filter blanks at the boundary so the engine never
        # has to defend against empty-string substring matches.
        raw = patch_dict["ai_handover_keywords"] or []
        config.ai_handover_keywords = [
            kw.strip() for kw in raw if isinstance(kw, str) and kw.strip()
        ]
    if "ai_system_prompt" in patch_dict:
        config.ai_system_prompt = (
            patch_dict["ai_system_prompt"] or None
        )

    await db.commit()
    await db.refresh(config)
    await audit.log(
        "integration.whatsapp.ai_settings_updated",
        entity_type="whatsapp_account",
        entity_id=config.id,
        user_id=user.legacy_uuid,
        before=before,
        after={
            "ai_handling_default_enabled": config.ai_handling_default_enabled,
            "ai_confidence_threshold": float(config.ai_confidence_threshold),
            "ai_handover_keywords": list(config.ai_handover_keywords or []),
            "ai_system_prompt": config.ai_system_prompt,
        },
    )
    return AISettingsRead(
        ai_handling_default_enabled=config.ai_handling_default_enabled,
        ai_confidence_threshold=float(config.ai_confidence_threshold),
        ai_handover_keywords=list(config.ai_handover_keywords or []),
        ai_system_prompt=config.ai_system_prompt,
    )
