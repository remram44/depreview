import logging
import sqlalchemy.event
from sqlalchemy import MetaData, Table, engine_from_config
from sqlalchemy.schema import Column, ForeignKey, ForeignKeyConstraint
from sqlalchemy.types import Boolean, Integer, String


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
    Column('repository', String, primary_key=True),
    Column('name', String, primary_key=True),
    Column('orig_name', String, nullable=False),
    Column('repository', String, nullable=True),
)

package_versions = Table(
    'package_versions',
    metadata,
    Column('repository', String, primary_key=True),
    Column('name', String, primary_key=True),
    Column('version', String, primary_key=True),
    ForeignKeyConstraint(
        ['repository', 'name'],
        ['packages.repository', 'packages.name'],
    ),
)

users = Table(
    'users',
    metadata,
    Column('id', Integer, primary_key=True),
    Column('disabled', Boolean, nullable=False),
    Column('login', String, nullable=False),
)

reviews = Table(
    'reviews',
    metadata,
    Column('id', Integer, primary_key=True),
    Column('repository', String, primary_key=True),
    Column('name', String, primary_key=True),
    Column('user_id', Integer, ForeignKey('users.id'), nullable=False),
    Column('type', String, nullable=False),
    Column('proof', String, nullable=False),
    ForeignKeyConstraint(
        ['repository', 'name'],
        ['packages.repository', 'packages.name'],
    ),
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
