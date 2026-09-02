import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

# this is the Alembic Config object
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import Base with all models registered
from src.models import Base
# Register new layered models with the shared metadata so autogenerate sees them.
from src.app.core.tenants import models as _organizations_models  # noqa: F401

from src.app.core.permissions import models as _permissions_models  # noqa: F401
from src.app.core.users import models as _users_models  # noqa: F401
from src.app.core.auth import models as _auth_models  # noqa: F401
from src.app.core.contacts import models as _contacts_models  # noqa: F401
from src.app.core.activities import models as _activities_models  # noqa: F401
from src.app.core.tasks import models as _tasks_models  # noqa: F401
from src.app.core.pipelines import models as _pipelines_models  # noqa: F401
from src.app.core.leads import models as _leads_models  # noqa: F401
from src.app.core.appointments import models as _appointments_models  # noqa: F401
from src.app.core.notifications import models as _notifications_models  # noqa: F401
from src.app.core.walk_ins import models as _walk_ins_models  # noqa: F401
from src.app.core.catalog import models as _catalog_models  # noqa: F401
from src.app.core.staff import models as _staff_models  # noqa: F401
from src.app.core.staff_portal import models as _staff_portal_models  # noqa: F401
from src.app.core.conversations import models as _conversations_models  # noqa: F401
from src.app.core.calls import models as _calls_models  # noqa: F401
from src.app.core.reviews import models as _reviews_models  # noqa: F401
from src.app.core.campaigns import models as _campaigns_models  # noqa: F401
from src.app.core.settings import models as _settings_models  # noqa: F401
from src.app.core.packs import models as _packs_models  # noqa: F401
from src.app.core.billing import models as _billing_models  # noqa: F401
from src.app.core.dev import models as _dev_models  # noqa: F401
from src.app.core.subscriptions import models as _subscriptions_models  # noqa: F401
from src.app.core.chatbots import models as _chatbots_models  # noqa: F401
from src.app.core.email import mailgun as _mailgun_pkg  # noqa: F401  # registers EmailInboundDlq
# Layer-2 pack models. Core/Alembic loads them so autogenerate sees
# the `fp_*` tables; the pack itself never imports core.
from src.app.packs.furniture.modules.inventory import (
    models as _fp_inventory_models,  # noqa: F401
)
from src.app.packs.furniture.modules.custom_orders import (
    models as _fp_custom_orders_models,  # noqa: F401
)
from src.app.packs.furniture.modules.field_ops import (
    models as _fp_field_ops_models,  # noqa: F401
)
target_metadata = Base.metadata

# Override sqlalchemy.url from environment
from src.core.db import DATABASE_URL
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("asyncpg", "asyncpg"))


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online():
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
