"""Org-delete cascade tests
(``tasks/ai-assistants`` Step 17).

Tests the cleanup hooks that fire when an organization is deleted:
  * SSE stream cancellation
  * Storage directory deletion
  * GDPR audit logging
"""

from __future__ import annotations

import uuid

import pytest

# Side-effect imports for FK resolution
import src.app.core.ai_assistants.models  # noqa: F401,E402


def test_sse_registry_has_cancel_by_org():
    """SseStreamRegistry has a cancel_by_org method for org deletion."""
    from src.app.core.ai_assistants.sse_registry import SseStreamRegistry

    registry = SseStreamRegistry()
    assert hasattr(registry, "cancel_by_org")
    assert callable(registry.cancel_by_org)


@pytest.mark.asyncio
async def test_sse_registry_cancel_by_org_returns_count(monkeypatch):
    """cancel_by_org returns the count of streams cancelled."""
    from src.app.core.ai_assistants.sse_registry import SseStreamRegistry

    registry = SseStreamRegistry()

    # Register fake streams.
    registry.register(embed_key_id=uuid.uuid4(), session_token="s1")
    registry.register(embed_key_id=uuid.uuid4(), session_token="s2")

    # Cancel by org.
    count = registry.cancel_by_org(uuid.uuid4())
    assert count == 2  # Both cancelled


def test_storage_delete_directory_exists():
    """LocalStorage.delete_directory method exists and is callable."""
    from src.app.shared.storage.local import LocalStorage

    storage = LocalStorage(root="./storage")
    assert hasattr(storage, "delete_directory")
    assert callable(storage.delete_directory)


async def test_storage_delete_directory_returns_count(tmp_path):
    """LocalStorage.delete_directory returns count of deleted files."""
    from src.app.shared.storage.local import LocalStorage

    storage = LocalStorage(root=str(tmp_path))
    org_id = str(uuid.uuid4())

    # Create nested structure.
    org_dir = tmp_path / org_id
    org_dir.mkdir()
    (org_dir / "file1.txt").write_text("content")
    (org_dir / "subdir").mkdir()
    (org_dir / "subdir" / "file2.txt").write_text("content")

    count = await storage.delete_directory(org_id)
    assert count == 2
    assert not org_dir.exists()


def test_gdpr_deletion_log_can_be_written():
    """GdprDeletionLog ORM model can be instantiated and would persist
    organization deletion metadata."""
    import uuid

    from src.app.core.ai_assistants.models import GdprDeletionLog

    org_id = uuid.uuid4()
    log = GdprDeletionLog(
        org_id=org_id,
        entity_type="organization",
        entity_count=1,
        deletion_reason="org_orphan_pending_deleted",
    )

    assert log.org_id == org_id
    assert log.entity_type == "organization"
    assert log.entity_count == 1
