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
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable, NamedTuple

# Walk targets: only the layered backend tree under src/app/core/ and
# src/app/packs/. Other roots (tests/, alembic/, scripts/, shared/)
# are intentionally excluded.
_ROOT = Path(__file__).resolve().parents[1] / "src" / "app"
_SCAN_ROOTS = (_ROOT / "core", _ROOT / "packs")


_SESSION_VARS = frozenset({"db", "session"})

_TRANSACTION_ATTRS = frozenset(
    {"commit", "rollback", "flush", "refresh"}
)

_ROUTER_FORBIDDEN_ATTRS = frozenset(
    {"execute", "add", "delete", "query", "merge"}
)

_SQLALCHEMY_CRUD_NAMES = frozenset(
    {"select", "insert", "update", "delete"}
)


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

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module and (
            node.module == "sqlalchemy"
            or node.module.startswith("sqlalchemy.")
        ):
            for alias in node.names:
                if alias.name in _SQLALCHEMY_CRUD_NAMES:
                    self.sqlalchemy_crud_imports.append(
                        (alias.name, node.lineno)
                    )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        # Match `<var>.<attr>(...)` where <var> is `db` or `session`.
        if isinstance(func, ast.Attribute) and isinstance(
            func.value, ast.Name
        ):
            if func.value.id in _SESSION_VARS:
                attr = func.attr
                if attr in _TRANSACTION_ATTRS:
                    self.transaction_calls.append((attr, node.lineno))
                elif attr in _ROUTER_FORBIDDEN_ATTRS:
                    self.crud_attr_calls.append((attr, node.lineno))
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
