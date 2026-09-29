"""Public-file patterns declared on `ModuleDescriptor` (r2-storage Step 4)."""

from __future__ import annotations

import uuid

import pytest

# Load the app first so pack modules import in the same order as at
# startup (importing a pack module cold trips a pipelines import cycle).
import src.app.main  # noqa: F401
from src.app.core.ai_assistants.module import MODULE as AI_ASSISTANTS
from src.app.core.catalog.module import MODULE as CATALOG
from src.app.core.module_registry import ModuleDescriptor, ModuleRegistry
from src.app.packs.furniture.modules.custom_orders.module import MODULE as CUSTOM_ORDERS
from src.app.packs.furniture.modules.field_ops.module import MODULE as FIELD_OPS
from src.app.packs.furniture.modules.inventory.module import MODULE as INVENTORY
from src.app.packs.real_estate.modules.property.module import MODULE as PROPERTY
from src.app.shared.storage.public_patterns import PublicFilePattern, is_public_key


def _u() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def patterns() -> list[PublicFilePattern]:
    registry = ModuleRegistry()
    for module in (CATALOG, AI_ASSISTANTS, INVENTORY, FIELD_OPS, CUSTOM_ORDERS, PROPERTY):
        registry.register(module)
    return registry.public_file_patterns()


@pytest.mark.parametrize(
    "pattern",
    [
        "*",
        "{uuid}",
        "catalog/*",
        "*/{uuid}/*",
        "{uuid}/*/x",
        "{uuid}/**",
        "Catalog/{uuid}/*",
        "{uuid}/../*",
        "{uuid}//*",
    ],
)
def test_invalid_patterns_rejected(pattern: str) -> None:
    with pytest.raises(ValueError):
        PublicFilePattern.parse(pattern)


def test_descriptor_rejects_bad_pattern() -> None:
    with pytest.raises(ValueError):
        ModuleDescriptor(
            id="x",
            name="X",
            icon="x",
            layer="core",
            route="/api/v1/x",
            frontend_route="/user/x",
            public_files=["catalog/*"],
        )


def test_every_module_image_key_is_public(patterns) -> None:
    org, row = _u(), _u()
    public_keys = [
        f"catalog/{org}/{row}.jpg",
        f"catalog/{org}/{row}-g2.png",
        f"{org}/ai_assistants/{row}/profile/1727600000000.webp",
        f"{org}/inventory/{row}/cover.jpg",
        f"{org}/field_visits/{row}/photo-{_u()}.jpg",
        f"{org}/custom_orders/{row}/photo-{_u()}.png",
        f"{org}/property/{row}/{_u()}.jpg",
    ]
    for key in public_keys:
        assert is_public_key(key, patterns), key


def test_private_keys_are_not_public(patterns) -> None:
    org, row = _u(), _u()
    private_keys = [
        f"{org}/call_recordings/{row}.mp3",
        f"{org}/imports/{row}/source.csv",
        f"{org}/imports/{row}/errors.csv",
        f"imports/{org}/{row}.csv",
        f"{org}/messages/{row}/invoice.pdf",
        f"{org}/quarantine/{row}/payload.json",
        f"{org}/ai_assistants/{row}.bin",
        f"{org}/ai_assistants/profile/{row}/x.png",
        f"{org}/ai_assistants/{row}/profile/nested/x.png",
        f"not-a-uuid/property/{row}/x.jpg",
        f"catalog/{org}/../{org}/x.jpg",
        f"{org}/property/{row}/../../call_recordings/x.mp3",
        "",
    ]
    for key in private_keys:
        assert not is_public_key(key, patterns), key
