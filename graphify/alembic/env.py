import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import models so they register on Base.metadata before autogenerate runs.
from graphify.server.config import get_settings, normalize_database_url
from graphify.server.db import Base
from graphify.server import models  # noqa: F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# DATABASE_URL comes from graphify/.env via get_settings(), not alembic.ini —
# keeps the connection string in one place.
#
# The bare environment variable wins when it is present. SERVICE_ROLE=migrate
# in the unified platform image promotes Neon's *direct* URL into DATABASE_URL
# for the migration process only (Alembic's DDL and advisory locks must not go
# through the pooled endpoint). That job also has none of the GitHub App or
# session secrets Settings requires, so calling get_settings() there would
# fail validation on fields a migration has no use for.
#
# Normalized through the same helper Settings uses: this path never builds a
# Settings object, so without it a quoted value or Neon's bare `postgresql://`
# scheme reaches SQLAlchemy unfixed and fails on a missing psycopg2.
_url = os.environ.get("DATABASE_URL")
config.set_main_option(
    "sqlalchemy.url",
    normalize_database_url(_url) if _url else get_settings().database_url,
)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
