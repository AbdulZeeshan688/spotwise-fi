"""Alembic environment. The DB URL comes from spotwise.config, never from alembic.ini."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from spotwise.config import get_settings
from spotwise.db.models import Base

config = context.config
# A caller (e.g. the eval loader) may pass another database in config.attributes
# "%" must be doubled: alembic's config parser treats it as interpolation (URL-encoded
# characters and passwords with % would otherwise crash)
database_url = config.attributes.get("database_url") or get_settings().database_url
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DB connection (`alembic upgrade head --sql`)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the live database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
