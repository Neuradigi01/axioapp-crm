"""Pin-test: backend modules follow the Router → Service → DAL layout.

Locks in the convention established by `tasks/dal-backfill/`. Fails CI
if any new code in `src/app/core/` or `src/app/packs/` violates:

  * **Transaction discipline.** ``session.commit / rollback / flush /
    refresh`` (or ``db.commit / ...``) may appear ONLY in ``service.py``
    or a ``*_service.py`` helper file. Routers and DAL files never own
    transactions.

  * **Router cleanliness.** ``router.py`` must not execute SQL: no
    ``session.execute / add / delete / query / merge``, no
    ``select() / insert() / update() / delete()`` SQLAlchemy
    constructor imports.

  * **DAL purity.** ``data_access.py`` must not commit. (Its SELECTs
    and ORM adds are expected.)

  * **Service cleanliness.** ``service.py`` (and ``*_service.py``
    helpers) must not run SQL directly — every ``session.execute /
    session.add`` lives behind a ``data_access.py`` function. Filter
    *composition* in service is fine; what's forbidden is the actual
    DB round-trip / staging call.

  * **Layer-direction imports.** ``router.py`` may not import any
    other module's ``data_access`` (Router → Service only).
    ``data_access.py`` may not import any module's ``service`` or
    ``router`` (DAL never depends upward).

  * **CRUD lives in DAL.** Any file under ``core/`` or ``packs/``
    that calls ``session.execute / add / add_all / delete / query
    / merge`` must be ``data_access.py``. Helper modules (Celery
    workers, webhook handlers, schedulers, integration sub-
    modules) inherited from before the layered layout are in a
    documented exception list — new helpers must route their SQL
    through a DAL function.

Note on cross-module data access from `service.py`: the project's
*preference* (manager call 2026-06-26) is for service files to route
data access through the target module's `service.py` when business
rules / permissions / validation live there, and to call another
module's `data_access.py` directly only when the operation is a
plain read/write with no business rules at stake. This is style, not
mechanically enforced — code review catches the judgment calls.

The full spec is in `CLAUDE.md` (Backend module layout section) and
`feedback_backend_layered_architecture.md` in user memory.

Allowed exceptions live in the lists below. Each exception names a
file + reason. Add to the list ONLY when a path was deliberately
left out of scope by a tasks/ track (e.g. Celery worker files
covered by a future polish step). New backend code in 2026-06-25
onward should never need to add an exception.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

# Walk targets: only the layered backend tree under src/app/core/ and
# src/app/packs/. Other roots (tests/, alembic/, scripts/, shared/)
# are intentionally excluded.
_ROOT = Path(__file__).resolve().parents[1] / "src" / "app"
_SCAN_ROOTS = (_ROOT / "core", _ROOT / "packs")


_SESSION_VARS = frozenset({"db", "session"})

_TRANSACTION_ATTRS = frozenset({"commit", "rollback", "flush", "refresh"})

_ROUTER_FORBIDDEN_ATTRS = frozenset({"execute", "add", "delete", "query", "merge"})

_SQLALCHEMY_CRUD_NAMES = frozenset({"select", "insert", "update", "delete"})


# Files allowed to call transaction-control methods despite NOT being
# named `service.py` / `*_service.py`. Each path is repo-relative from
# `src/app/`. Add a comment whenever a new entry lands.
#
# All of these were out of scope for the dal-backfill track (Celery
# workers, webhook handlers, integration sub-modules, pack installers,
# legacy *_router.py helpers that pre-date the layout). They open
# their own sessions or run inside short-lived RequestContext
# scopes. A future polish track can refactor them to call service.py
# wrappers; until then this list pins the known state.
_TRANSACTION_EXCEPTIONS: dict[str, str] = {
    # --- Campaigns helpers
    "core/campaigns/ab_decider.py": "Campaign A/B decider (own session)",
    "core/campaigns/tasks.py": "Celery campaign worker",
    # --- Email module helpers (Celery + sync daemon + Gmail/Microsoft sub-modules)
    "core/email/tasks.py": "Celery email worker",
    "core/email/sync_daemon.py": "Email sync daemon",
    "core/email/gmail/router.py": "Gmail OAuth sub-router (pre-layout)",
    "core/email/gmail/send.py": "Gmail send helper (own txn)",
    "core/email/microsoft/router.py": "Microsoft OAuth sub-router (pre-layout)",
    "core/email/microsoft/send.py": "Microsoft send helper (own txn)",
    "core/email/tracking/router.py": "Email open/click tracking router",
    # --- Email sequences scheduler
    "core/email_sequences/scheduler.py": "Email sequence scheduler (Celery)",
    # --- Integrations sub-module helpers
    "core/integrations/google/dlq.py": "Google ad DLQ writer",
    "core/integrations/meta/data_deletion.py": "Meta data-deletion handler",
    "core/integrations/meta/router.py": "Meta sub-router (pre-layout)",
    "core/integrations/meta/subscriptions.py": "Meta webhook subscription manager",
    "core/integrations/meta/tasks.py": "Celery Meta worker",
    "core/integrations/whatsapp/automation_router.py": "WA automation sub-router",
    "core/integrations/whatsapp/business_profile.py": "WA business profile writer",
    "core/integrations/whatsapp/embedded_signup.py": "WA Embedded Signup flow",
    "core/integrations/whatsapp/flows_router.py": "WA Flows sub-router",
    "core/integrations/whatsapp/health_tasks.py": "WA health-check tasks",
    "core/integrations/whatsapp/router.py": "WA main sub-router (pre-layout)",
    "core/integrations/whatsapp/status.py": "WA status webhook handler",
    "core/integrations/whatsapp/templates.py": "WA template submission helper",
    # --- Leads sub-module helpers
    "core/leads/imports/presets.py": "Lead-import preset CRUD helper",
    "core/leads/imports/tasks.py": "Bulk-import Celery worker",
    # --- Packs installer (core) — orchestrates seed inserts
    "core/packs/installer.py": "Pack installer (own txn semantics)",
    # --- Permissions role-template seeder (called from service)
    "core/permissions/role_templates.py": "Role template seeder (flush only)",
    # --- Subscriptions webhook handlers (Stripe)
    "core/subscriptions/webhooks/router.py": "Stripe webhook sub-router",
    "core/subscriptions/webhooks/handlers/checkout_completed.py": "Stripe checkout webhook handler",
    "core/subscriptions/webhooks/handlers/invoice_failed.py": "Stripe invoice-failed handler",
    "core/subscriptions/webhooks/handlers/invoice_paid.py": "Stripe invoice-paid handler",
    "core/subscriptions/webhooks/handlers/subscription_cancelled.py": "Stripe sub-cancelled handler",
    "core/subscriptions/webhooks/handlers/subscription_updated.py": "Stripe sub-updated handler",
    # --- Templates sub-module helpers
    "core/templates/external_submission.py": "External template-provider submission",
    "core/templates/test_send.py": "Test-send orchestrator",
    # --- Tenants ownership-transfer helper
    "core/tenants/ownership.py": "Ownership-transfer flow (own txn)",
    # --- Conversation adapters
    "core/conversations/adapters/email.py": "Email adapter (own session for inbound)",
    # --- Integrations DLQ
    "core/integrations/dlq.py": "Webhook DLQ writer",
    # --- WhatsApp integration sub-modules
    "core/integrations/whatsapp/auto_reply.py": "WA auto-reply dispatcher",
    "core/integrations/whatsapp/keyword_engine.py": "WA keyword engine",
    "core/integrations/whatsapp/assignment_engine.py": "WA assignment engine",
    "core/integrations/whatsapp/ai_handler.py": "WA AI reply pipeline",
    "core/integrations/whatsapp/block_list.py": "WA block-list writer",
    "core/integrations/whatsapp/connect.py": "WA active-config helper",
    "core/integrations/whatsapp/quick_links.py": "QR / wa.me attribution",
    # --- Leads sub-helpers
    "core/leads/scoring.py": "Lead scoring recomputer",
    # --- Subscriptions Celery tasks (one of several already listed above)
    "core/subscriptions/tasks.py": "Celery subscription rollover worker",
    # --- Templates helpers
    "core/templates/sms_extension.py": "SMS DLT extension writer",
    "core/templates/workflow.py": "Template review workflow",
    # --- Workflows module helpers (Celery beat tasks + engine + trigger
    # handler — own session semantics, run outside a request context)
    "core/workflows/engine.py": "Workflow execution engine (own txn / session)",
    "core/workflows/tasks.py": "Celery workflow workers (sweeps + A/B + cached counters)",
    "core/workflows/trigger_handlers.py": "Event-bus subscriber (own txn)",
    # --- Chatbots module helpers (bus subscriber + engine + Celery
    # workers — own session semantics, run outside a request context).
    # Mirrors the workflows exemption.
    "core/chatbots/engine.py": "Chatbot execution engine (own txn / session)",
    "core/chatbots/trigger_matcher.py": "Chatbot bus subscriber + matcher (own txn)",
    "core/chatbots/tasks.py": "Celery chatbot workers (process_step + sweep_test_runs)",
    "core/chatbots/channel_bridge.py": "Bot-outbound sender (own txn, mirrors WA auto_reply.py)",
    "core/chatbots/nodes/template.py": "Template node retags outbound Message as bot-authored",
    "core/chatbots/nodes/ask_question.py": "Ask-Question handler commits after save-target write",
    "core/chatbots/nodes/ask_address.py": "Ask-Address handler commits after save-target write",
    "core/chatbots/nodes/ask_location.py": "Ask-Location handler commits after save-target write",
    "core/chatbots/nodes/ask_media.py": "Ask-Media handler commits after save-target write",
    # --- Pack billing module — router-only PDF generation shell, completion deferred
    "packs/furniture/modules/billing/router.py": "Pack billing PDF stub (Phase 4 follow-up)",
}


# Files allowed to do `session.execute / add / delete / query` despite
# being named `router.py`. Covers the same legacy `*_router.py` sub-
# routers + webhook handlers + pack billing stub as the transaction
# exception list. New routers must route through service.
_ROUTER_EXCEPTIONS: dict[str, str] = {
    "core/email/tracking/router.py": "Email open/click tracker",
    "core/subscriptions/webhooks/router.py": "Stripe webhook router",
    "packs/furniture/modules/billing/router.py": "Pack billing PDF stub",
}


# Files allowed to import sqlalchemy CRUD constructors despite being
# `router.py`. Same set as `_ROUTER_EXCEPTIONS`.
_ROUTER_IMPORT_EXCEPTIONS: dict[str, str] = {
    "core/email/tracking/router.py": "Email open/click tracker",
    "core/subscriptions/webhooks/router.py": "Stripe webhook router",
    "packs/furniture/modules/billing/router.py": "Pack billing PDF stub",
}


# Files allowed to call `session.execute / add / delete / query` despite
# being a `service.py`. Read-only aggregation modules whose entire job
# is composing ad-hoc analytical queries — moving each into a single-
# use DAL function would be busywork without changing the architecture
# meaningfully (no transaction discipline, no router boundary).
# Files allowed to import another module's `data_access` from inside a
# `router.py`. Only legacy `*_router.py`-style files + webhook handlers
# that pre-date the layered layout — same set as `_ROUTER_EXCEPTIONS`,
# kept separate so the two rules can drift independently if needed.
_ROUTER_DAL_IMPORT_EXCEPTIONS: dict[str, str] = {
    "core/email/tracking/router.py": "Email open/click tracker (pre-layout)",
    "core/subscriptions/webhooks/router.py": "Stripe webhook router",
    "packs/furniture/modules/billing/router.py": "Pack billing PDF stub",
}


# Files allowed to import another module's `service` from inside a
# `data_access.py`. Should always be empty — DAL never depends upward.
# This list exists so a future deliberate carve-out can be documented
# rather than landing as silent drift.
_DAL_SERVICE_IMPORT_EXCEPTIONS: dict[str, str] = {}


# Helper files (Celery workers, schedulers, webhook handlers,
# integration sub-modules) allowed to run SQL directly even though
# they aren't `data_access.py`. Inherited from before the layered
# layout was established — the dal-backfill track deliberately left
# them out of scope. A future polish track moves their SQL into
# their module's DAL; until then this list locks the known state.
#
# New helper code under core/ or packs/ should call into a
# `data_access.py` function, not do its own SQL. If you find yourself
# needing to add an entry here, ask whether you should be writing a
# DAL helper instead.
_HELPER_CRUD_EXCEPTIONS: dict[str, str] = {
    # --- FastAPI dependency that loads the current user
    "core/auth/dependencies.py": "Auth dependency (loads current user from JWT)",
    # --- Campaigns engine helpers
    "core/campaigns/ab_decider.py": "A/B winner decider (own session)",
    "core/campaigns/tasks.py": "Celery campaign worker",
    # --- Contacts CSV export
    "core/contacts/data_export.py": "Contacts CSV exporter",
    # --- Conversation adapter (inbound email)
    "core/conversations/adapters/email.py": "Email adapter (own session)",
    # --- Email module helpers
    "core/email/gmail/push.py": "Gmail push subscriptions",
    "core/email/gmail/sync.py": "Gmail message sync",
    "core/email/microsoft/sync.py": "Outlook message sync",
    "core/email/microsoft/webhook.py": "Outlook webhook handler",
    "core/email/tasks.py": "Celery email worker",
    "core/email_sequences/scheduler.py": "Email sequence scheduler (Celery beat)",
    # --- Integrations
    "core/integrations/dlq.py": "Webhook DLQ writer",
    "core/integrations/google/tasks.py": "Celery Google Ads worker",
    "core/integrations/meta/ads_lookup.py": "Meta ads lookup helper",
    "core/integrations/meta/data_deletion.py": "Meta data-deletion handler",
    "core/integrations/meta/subscriptions.py": "Meta webhook subscription manager",
    "core/integrations/meta/tasks.py": "Celery Meta worker",
    "core/integrations/status.py": "Integration health-status reader",
    # --- WhatsApp integration sub-modules
    "core/integrations/whatsapp/ai_handler.py": "WA AI reply pipeline",
    "core/integrations/whatsapp/assignment_engine.py": "WA assignment engine",
    "core/integrations/whatsapp/auto_reply.py": "WA auto-reply dispatcher",
    "core/integrations/whatsapp/automation_router.py": "WA automation sub-router",
    "core/integrations/whatsapp/block_list.py": "WA block-list writer",
    "core/integrations/whatsapp/connect.py": "WA active-config helper",
    "core/integrations/whatsapp/embedded_signup.py": "WA Embedded Signup flow",
    "core/integrations/whatsapp/flows_router.py": "WA Flows sub-router",
    "core/integrations/whatsapp/health_tasks.py": "WA health-check tasks",
    "core/integrations/whatsapp/keyword_engine.py": "WA keyword engine",
    "core/integrations/whatsapp/quick_links.py": "QR / wa.me attribution",
    "core/integrations/whatsapp/quick_links_router.py": "WA quick-links sub-router",
    "core/integrations/whatsapp/status.py": "WA status webhook handler",
    "core/integrations/whatsapp/templates.py": "WA template submission helper",
    "core/integrations/whatsapp/templates_analytics.py": "WA template analytics",
    # --- Leads helpers
    "core/leads/csv_export.py": "Leads CSV exporter",
    "core/leads/dedup.py": "Lead dedupe checker",
    "core/leads/imports/dedup.py": "Bulk-import dedupe",
    "core/leads/imports/presets.py": "Lead-import preset CRUD helper",
    "core/leads/imports/targets.py": "Lead-import target resolver",
    "core/leads/imports/tasks.py": "Bulk-import Celery worker",
    "core/leads/routing.py": "Lead round-robin router",
    "core/leads/scoring.py": "Lead scoring recomputer",
    # --- Packs installer
    "core/packs/installer.py": "Pack installer (own txn semantics)",
    # --- Permissions seeder
    "core/permissions/role_templates.py": "Role template seeder",
    # --- Reporting analytics
    "core/reporting/ad_attribution.py": "Ad-attribution analytics",
    "core/reporting/campaign_analytics.py": "Campaign analytics",
    "core/reporting/whatsapp_analytics.py": "WhatsApp analytics",
    # --- Subscriptions
    "core/subscriptions/lifecycle.py": "Subscription lifecycle helper",
    "core/subscriptions/middleware.py": "Subscription gating middleware",
    "core/subscriptions/notifications.py": "Subscription notifications",
    "core/subscriptions/signup_hook.py": "Trial subscription on signup",
    "core/subscriptions/tasks.py": "Celery subscription rollover worker",
    "core/subscriptions/webhooks/handlers/__init__.py": "Stripe webhook handlers __init__",
    "core/subscriptions/webhooks/handlers/checkout_completed.py": "Stripe checkout completed",
    "core/subscriptions/webhooks/handlers/invoice_failed.py": "Stripe invoice failed",
    "core/subscriptions/webhooks/handlers/invoice_paid.py": "Stripe invoice paid",
    "core/subscriptions/webhooks/handlers/subscription_cancelled.py": "Stripe sub cancelled",
    "core/subscriptions/webhooks/handlers/subscription_updated.py": "Stripe sub updated",
    # --- Templates helpers
    "core/templates/render.py": "Template render helper",
    "core/templates/sms_extension.py": "SMS DLT extension writer",
    "core/templates/test_send.py": "Template test-send",
    "core/templates/workflow.py": "Template review workflow",
    # --- Tenants ownership transfer
    "core/tenants/ownership.py": "Ownership-transfer flow",
    # --- Workflows module helpers (engine + Celery workers + bus handler).
    # All run their own session in Celery / bus context, not via a request.
    "core/workflows/engine.py": "Workflow execution engine (CRUD on runs / step_runs)",
    "core/workflows/tasks.py": "Celery workflow workers (sweeps + cached counters)",
    "core/workflows/trigger_handlers.py": "Event-bus subscriber (lookup + start_run)",
    "core/workflows/ab_testing.py": "A/B testing engine helper (own session)",
    "core/workflows/diagnostics.py": "Diagnostics trace (read-only, own session)",
    # --- Chatbots module helpers (bus subscriber + engine + Celery
    # workers). Own session semantics; the matcher + engine + sweeper
    # run under their own async_session, not a request-scoped one.
    "core/chatbots/engine.py": "Chatbot execution engine (CRUD on runs / step_runs)",
    "core/chatbots/trigger_matcher.py": "Chatbot bus subscriber (lookup + start_run + diagnostics)",
    "core/chatbots/tasks.py": "Celery chatbot workers (sweeps + step processor)",
    "core/chatbots/channel_bridge.py": "Bot-outbound sender (Message insert + conv update)",
}


_SERVICE_SQL_EXCEPTIONS: dict[str, str] = {
    "core/dashboard/service.py": "Dashboard widget aggregations (read-only, no models)",
    "core/reporting/service.py": "Reporting aggregations (read-only, no models)",
    # --- WhatsApp integration helper services
    # Deferred along with the rest of the WhatsApp tree (see
    # `_TRANSACTION_EXCEPTIONS` above); a future integrations polish
    # track refactors them through a proper DAL.
    "core/contacts/consent_service.py": "Consent helper (pre-layout)",
    "core/integrations/whatsapp/flows_service.py": "WA Flows helper (pre-layout)",
    "core/integrations/whatsapp/health_service.py": "WA health helper (pre-layout)",
    "core/integrations/whatsapp/templates_service.py": "WA templates helper (pre-layout)",
}


class _Violation(NamedTuple):
    path: str
    line: int
    kind: str
    detail: str


def _iter_python_files(root: Path) -> Iterable[Path]:
    """Yield every `.py` file under `root` excluding ``__pycache__``."""
    if not root.exists():
        return
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def _relative(path: Path) -> str:
    """Path relative to ``src/app/`` with forward slashes."""
    return path.relative_to(_ROOT).as_posix()


def _is_service_file(path: Path) -> bool:
    """Service files own transaction control. `*_service.py` helpers
    (e.g. `notes_service.py`, `config_service.py`) follow the same
    contract."""
    name = path.name
    return name == "service.py" or name.endswith("_service.py")


def _is_router_file(path: Path) -> bool:
    return path.name == "router.py"


def _is_dal_file(path: Path) -> bool:
    return path.name == "data_access.py"


class _ArchitectureVisitor(ast.NodeVisitor):
    """Walks a single file's AST and records architecture-relevant
    call / import sites."""

    def __init__(self) -> None:
        self.transaction_calls: list[tuple[str, int]] = []
        self.crud_attr_calls: list[tuple[str, int]] = []
        self.sqlalchemy_crud_imports: list[tuple[str, int]] = []
        # Layer-direction imports we track:
        #   * `from src.app.{core,packs}.<x>.data_access import ...`
        #   * `from src.app.{core,packs}.<x> import data_access`
        #   * `from src.app.{core,packs}.<x>.service import ...`
        #   * `from src.app.{core,packs}.<x> import service`
        #   * same shape for `router`
        # Each entry is `(target_layer, full_module_path, lineno)` where
        # `target_layer` is one of `"data_access"`, `"service"`, `"router"`.
        self.layer_imports: list[tuple[str, str, int]] = []

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module and (node.module == "sqlalchemy" or node.module.startswith("sqlalchemy.")):
            for alias in node.names:
                if alias.name in _SQLALCHEMY_CRUD_NAMES:
                    self.sqlalchemy_crud_imports.append((alias.name, node.lineno))
        if node.module and node.module.startswith("src.app."):
            mod = node.module
            # Form 1: `from ...x.data_access import ...`
            for layer in ("data_access", "service", "router"):
                if mod.endswith(f".{layer}") or mod == f"src.app.{layer}":
                    self.layer_imports.append((layer, mod, node.lineno))
                    break
            else:
                # Form 2: `from ...x import data_access` (etc.)
                for alias in node.names:
                    if alias.name in ("data_access", "service", "router"):
                        self.layer_imports.append((alias.name, f"{mod}.{alias.name}", node.lineno))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        # Match `<var>.<attr>(...)` where <var> is `db` or `session`.
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id in _SESSION_VARS:
                attr = func.attr
                if attr in _TRANSACTION_ATTRS:
                    self.transaction_calls.append((attr, node.lineno))
                elif attr in _ROUTER_FORBIDDEN_ATTRS:
                    self.crud_attr_calls.append((attr, node.lineno))
        # `session.add_all(...)` is the bulk variant of `session.add`
        # — treat it the same way (forbidden in routers, fine in DAL
        # via wrapper, allowed in DAL directly).
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id in _SESSION_VARS and func.attr == "add_all":
                self.crud_attr_calls.append(("add_all", node.lineno))
        self.generic_visit(node)


def _scan_file(path: Path) -> _ArchitectureVisitor:
    visitor = _ArchitectureVisitor()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        # Can't enforce on un-parseable files; surface elsewhere.
        return visitor
    visitor.visit(tree)
    return visitor


def _collect_violations() -> list[_Violation]:
    """Walk every Python file under the scan roots and return the
    consolidated violation list."""
    violations: list[_Violation] = []
    for root in _SCAN_ROOTS:
        for path in _iter_python_files(root):
            rel = _relative(path)
            visitor = _scan_file(path)

            # --- Transaction control rule.
            if (
                visitor.transaction_calls
                and not _is_service_file(path)
                and rel not in _TRANSACTION_EXCEPTIONS
            ):
                for attr, lineno in visitor.transaction_calls:
                    violations.append(
                        _Violation(
                            path=rel,
                            line=lineno,
                            kind="transaction_outside_service",
                            detail=(
                                f"`db.{attr}()` may only appear in "
                                "service.py / *_service.py — file is "
                                f"`{path.name}`."
                            ),
                        )
                    )

            # --- Router cleanliness rule.
            if _is_router_file(path):
                if rel not in _ROUTER_EXCEPTIONS:
                    for attr, lineno in visitor.crud_attr_calls:
                        violations.append(
                            _Violation(
                                path=rel,
                                line=lineno,
                                kind="orm_crud_in_router",
                                detail=(
                                    f"`db.{attr}()` is not allowed in "
                                    "router.py — route through service."
                                ),
                            )
                        )
                if rel not in _ROUTER_IMPORT_EXCEPTIONS:
                    for name, lineno in visitor.sqlalchemy_crud_imports:
                        violations.append(
                            _Violation(
                                path=rel,
                                line=lineno,
                                kind="sqlalchemy_import_in_router",
                                detail=(
                                    f"`from sqlalchemy import {name}` "
                                    "is not allowed in router.py — "
                                    "route through service."
                                ),
                            )
                        )

            # --- CRUD-in-DAL rule (whole-tree).
            #
            # Catches helper modules (Celery workers, schedulers,
            # webhook handlers, integration sub-modules) that run
            # SQL outside the 5-file layered layout. The router and
            # service rules above already handle their respective
            # files; this rule fires on everything else.
            is_layered = _is_router_file(path) or _is_service_file(path) or _is_dal_file(path)
            if not is_layered and visitor.crud_attr_calls and rel not in _HELPER_CRUD_EXCEPTIONS:
                for attr, lineno in visitor.crud_attr_calls:
                    violations.append(
                        _Violation(
                            path=rel,
                            line=lineno,
                            kind="crud_outside_dal",
                            detail=(
                                f"`db.{attr}()` in `{path.name}` — "
                                "CRUD belongs in data_access.py. "
                                "Move the query into the module's "
                                "DAL and call it from here."
                            ),
                        )
                    )

            # --- DAL purity rule.
            if _is_dal_file(path):
                for attr, lineno in visitor.transaction_calls:
                    violations.append(
                        _Violation(
                            path=rel,
                            line=lineno,
                            kind="transaction_in_dal",
                            detail=(
                                f"`db.{attr}()` is not allowed in "
                                "data_access.py — caller (service) "
                                "owns the transaction."
                            ),
                        )
                    )

            # --- Layer-direction import rules.
            if _is_router_file(path) and rel not in _ROUTER_DAL_IMPORT_EXCEPTIONS:
                for layer, mod, lineno in visitor.layer_imports:
                    if layer == "data_access":
                        violations.append(
                            _Violation(
                                path=rel,
                                line=lineno,
                                kind="dal_import_in_router",
                                detail=(
                                    f"`{mod}` imported in router.py — "
                                    "Router → Service only. Add a "
                                    "service wrapper and call that."
                                ),
                            )
                        )
            if _is_dal_file(path) and rel not in _DAL_SERVICE_IMPORT_EXCEPTIONS:
                for layer, mod, lineno in visitor.layer_imports:
                    if layer in ("service", "router"):
                        violations.append(
                            _Violation(
                                path=rel,
                                line=lineno,
                                kind=f"{layer}_import_in_dal",
                                detail=(
                                    f"`{mod}` imported in "
                                    "data_access.py — DAL never "
                                    "depends upward on service / "
                                    "router."
                                ),
                            )
                        )

            # --- Service cleanliness rule.
            #
            # Only the *execution* side is enforced — `session.execute`,
            # `session.add`, `session.add_all`, `session.delete`,
            # `session.merge`, `session.query`. Composition (importing
            # `select` to build a statement the DAL then executes via a
            # paginate-style wrapper) stays allowed: it's the "filter
            # DSL gray area" the dal-backfill track explicitly left in
            # service for leads/tasks pipeline reads.
            if _is_service_file(path) and rel not in _SERVICE_SQL_EXCEPTIONS:
                for attr, lineno in visitor.crud_attr_calls:
                    violations.append(
                        _Violation(
                            path=rel,
                            line=lineno,
                            kind="orm_crud_in_service",
                            detail=(
                                f"`db.{attr}()` is not allowed in "
                                "service.py — wrap in a "
                                "data_access.py helper."
                            ),
                        )
                    )

    return violations


def _format(violations: list[_Violation]) -> str:
    if not violations:
        return ""
    by_kind: dict[str, list[_Violation]] = defaultdict(list)
    for v in violations:
        by_kind[v.kind].append(v)
    lines: list[str] = []
    for kind, items in sorted(by_kind.items()):
        lines.append(f"  [{kind}] ({len(items)} violation(s)):")
        for v in sorted(items, key=lambda x: (x.path, x.line)):
            lines.append(f"    {v.path}:{v.line} — {v.detail}")
    return "\n".join(lines)


def test_layered_architecture_convention_holds() -> None:
    """The backfill bucket finished in `tasks/dal-backfill/`. Any new
    violation here is fresh drift — fix the file or add an exception
    with a documented reason."""
    violations = _collect_violations()
    assert violations == [], (
        "Layered-architecture convention violated (see CLAUDE.md "
        "'Backend module layout'):\n\n" + _format(violations)
    )
