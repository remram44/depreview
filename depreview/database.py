import logging
import sqlalchemy.event
from sqlalchemy import MetaData, Table, engine_from_config
from sqlalchemy.schema import Column, ForeignKey, ForeignKeyConstraint
from sqlalchemy.types import Boolean, DateTime, Integer, String


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
    Column('norm_name', String, primary_key=True),
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
    Column('norm_name', String, primary_key=True),
    Column('version', String, primary_key=True),
    Column('release_date', DateTime, nullable=False),
    Column('yanked', Boolean, nullable=False),
    ForeignKeyConstraint(
        ['registry', 'norm_name'],
        ['packages.registry', 'packages.norm_name'],
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
    Column('norm_name', String),
    Column('user_id', Integer, ForeignKey('users.id'), nullable=False),
    Column('type', String, nullable=False),
    Column('proof', String, nullable=False),
    Column('created', DateTime, nullable=False),
    Column('trust', Integer, nullable=False),
    ForeignKeyConstraint(
        ['registry', 'norm_name'],
        ['packages.registry', 'packages.norm_name'],
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

dependency_lists = Table(
    'dependency_lists',
    metadata,
    Column('id', Integer, primary_key=True),
    Column('created', DateTime, nullable=False),
    Column('registry', String, nullable=False),
    Column('format', String, nullable=False),
)

dependency_list_items = Table(
    'dependency_list_items',
    metadata,
    Column('list_id', Integer, primary_key=True),
    Column('norm_name', String, primary_key=True),
    Column('version', String),
    Column('direct', Boolean, nullable=True),
    Column('depends_on', String, nullable=True),
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
