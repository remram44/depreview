import logging
import sqlalchemy.event
from sqlalchemy import MetaData, Table, desc, engine_from_config
from sqlalchemy.schema import Column, ForeignKey, ForeignKeyConstraint
from sqlalchemy.types import Boolean, DateTime, Integer, String

from .registries.base import Package, PackageVersion


logger = logging.getLogger(__name__)


metadata = MetaData(naming_convention={
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
})


packages = Table(
    'packages',
    metadata,
    Column('registry', String, primary_key=True),
    Column('name', String, primary_key=True),
    Column('last_refresh', DateTime, nullable=False),
    Column('orig_name', String, nullable=False),
    Column('author', String, nullable=True),
    Column('description', String, nullable=True),
    Column('description_type', String, nullable=True),
    Column('repository', String, nullable=True),
)

package_versions = Table(
    'package_versions',
    metadata,
    Column('registry', String, primary_key=True),
    Column('name', String, primary_key=True),
    Column('version', String, primary_key=True),
    Column('release_date', DateTime, nullable=False),
    Column('yanked', Boolean, nullable=False),
    ForeignKeyConstraint(
        ['registry', 'name'],
        ['packages.registry', 'packages.name'],
    ),
)

users = Table(
    'users',
    metadata,
    Column('id', Integer, primary_key=True),
    Column('disabled', Boolean, nullable=False),
    Column('login', String, nullable=False),
    Column('name', String, nullable=False),
)

statements = Table(
    'statements',
    metadata,
    Column('id', Integer, primary_key=True),
    Column('registry', String),
    Column('name', String),
    Column('user_id', Integer, ForeignKey('users.id'), nullable=False),
    Column('type', String, nullable=False),
    Column('proof', String, nullable=False),
    Column('created', DateTime, nullable=False),
    Column('trust', Integer, nullable=False),
    ForeignKeyConstraint(
        ['registry', 'name'],
        ['packages.registry', 'packages.name'],
    ),
)

reviews = Table(
    'reviews',
    metadata,
    Column(
        'statement_id', Integer,
        ForeignKey('statements.id'),
        primary_key=True,
    ),
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('type', String, nullable=False),
)


def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def connect(db_url):
    """Connect to the database.
    """
    if isinstance(db_url, dict):
        db_dict = db_url
        db_url = db_dict['url']
    else:
        db_dict = {'url': db_url}

    logger.info("Connecting to SQL database %r", db_url)
    if db_url.startswith('sqlite:'):
        db_dict['connect_args'] = {'check_same_thread': False}
    engine = engine_from_config(db_dict, prefix='')
    # logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

    if db_url.startswith('sqlite:'):
        sqlalchemy.event.listen(
            engine,
            "connect",
            set_sqlite_pragma,
        )

    return engine


def get_package(db, registry, normalized_name):
    package = db.execute(
        sqlalchemy.select([
            packages.c.orig_name,
            packages.c.last_refresh,
            packages.c.repository,
            packages.c.author,
            packages.c.description,
            packages.c.description_type,
        ])
        .select_from(packages)
        .where(
            packages.c.registry == registry,
            packages.c.name == normalized_name,
        )
        .limit(1)
    ).first()
    if not package:
        return None
    [
        orig_name,
        last_refresh,
        repository,
        author,
        description,
        description_type,
    ] = package

    versions = db.execute(
        sqlalchemy.select([
            package_versions.c.version,
            package_versions.c.release_date,
            package_versions.c.yanked,
        ])
        .select_from(package_versions)
        .where(
            package_versions.c.registry == registry,
            package_versions.c.name == normalized_name,
        )
        .order_by(desc(package_versions.c.release_date))
    )
    versions = {
        version: PackageVersion(
            version,
            release_date=release_date,
            yanked=yanked,
        )
        for version, release_date, yanked in versions
    }

    package = Package(
        registry,
        orig_name,
        versions,
        author=author,
        description=description,
        description_type=description_type,
        repository=repository,
        last_refresh=last_refresh,
    )
    return package


def get_statements(db, registry, normalized_name):
    return db.execute(
        sqlalchemy.select([
            statements.c.id,
            statements.c.type,
            statements.c.proof,
            statements.c.created,
            statements.c.trust,
        ])
        .where(
            statements.c.registry == registry,
            statements.c.name == normalized_name,
        )
    )
