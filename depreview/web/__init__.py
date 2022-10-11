import aiohttp
import bleach
from datetime import datetime, timedelta
import docutils.core
import logging
import markdown
from markupsafe import Markup
import os
from quart import Quart, render_template, redirect, url_for, request
import sqlalchemy
from sqlalchemy import and_, desc

from .. import crypto
from .. import database
from ..decision import annotate_versions
from .. import parse
from ..registries import get_registry, get_all_registry_names
from ..registries.base import Package, PackageVersion


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


MAX_AGE = timedelta(hours=6)


app = Quart(__name__)


db = database.connect(os.environ['DATABASE_URL'])


def clean_html(html):
    return bleach.clean(
        html,
        tags=[
            'p', 'br', 'a', 'img', 'pre', 'code', 'section',
            'h1', 'h2', 'h3', 'h4', 'h5',
            'strong', 'em', 'b', 'u', 'ul', 'ol', 'li',
        ],
        attributes={'a': ['href', 'title'], 'img': ['src', 'width', 'height']},
        strip=True,
    )


def render_description(description, description_type):
    if description_type == 'text/markdown':
        return clean_html(markdown.markdown(description))
    elif description_type == 'text/x-rst':
        return clean_html(docutils.core.publish_parts(
            description,
            writer_name='html',
        )['html_body'])

    return '<pre>%s</pre>' % (
        description.replace('&', '&amp;').replace('<', '&lt;')
    )


@app.get('/')
async def index():
    latest_changes = db.execute(
        sqlalchemy.select([
            database.statements.c.created,
            database.statements.c.registry,
            database.statements.c.norm_name,
            database.statements.c.type,
            database.statements.c.proof,
            database.statements.c.user_id,
            database.statements.c.trust,
            database.users.c.login,
            database.users.c.name,
        ])
        .select_from(
            database.statements
            .join(
                database.users,
                database.statements.c.user_id == database.users.c.id,
            )
        )
        .order_by(desc(database.statements.c.created))
        .limit(10)
    )
    return await render_template(
        'index.html',
        registry_names=get_all_registry_names(),
        latest_changes=latest_changes,
    )


@app.get('/p/<registry>/<name>')
async def package(registry, name):
    registry_obj = get_registry(registry)
    if registry_obj is None:
        return await render_template(
            'package_notfound.html',
            error='No such registry',
        ), 404

    # Use the registry plugin to normalize the name
    norm_name = registry_obj.normalize_name(name)
    if norm_name != name:
        return redirect(
            url_for('package', registry=registry, name=norm_name),
            301,
        )
    del name

    package = await get_package(registry_obj, norm_name)

    # Get the statements
    statements = list(db.execute(
        sqlalchemy.select([
            database.statements.c.id,
            database.statements.c.type,
            database.statements.c.proof,
            database.statements.c.created,
            database.statements.c.trust,
        ])
        .where(
            database.statements.c.registry == registry,
            database.statements.c.norm_name == norm_name,
        )
    ))

    # Annotate versions with whether they are outdated
    versions = annotate_versions(
        registry_obj,
        package.versions,
        statements,
    )

    return await render_template(
        'package.html',
        package=package,
        versions=versions,
        link=registry_obj.get_link(norm_name),
        rendered_description=Markup(render_description(
            package.description,
            package.description_type,
        )),
    )


@app.post('/search')
async def search_package():
    form = await request.form
    registry = form['registry']
    name = form['name']

    registry_obj = get_registry(registry)
    if registry_obj is None:
        return await render_template(
            'package_notfound.html',
            error='No such registry',
        ), 404
    norm_name = registry_obj.normalize_name(name)

    return redirect(
        url_for('package', registry=registry, name=norm_name),
        301,
    )


@app.post('/upload-list')
async def upload_list():
    files = await request.files
    all_dependencies = None
    direct_dependencies = None
    registry = list_format = None
    # Note: use files.get(...) to check for files
    # If a file input was left empty, the dict is still populated, but the
    # FileStorage object is false-ish
    try:
        if 'poetry-lock' in files or 'pyproject-toml' in files:
            # Python Poetry
            registry = 'pypi'
            list_format = 'poetry'
            if files.get('poetry-lock'):
                all_dependencies = parse.poetry_lock(
                    files['poetry-lock'],
                )
            if files.get('pyproject-toml'):
                direct_dependencies = parse.pyproject_toml(
                    files['pyproject-toml'],
                )
            if not all_dependencies:
                all_dependencies = direct_dependencies
        elif 'requirements-txt' in files:
            # Python requirements.txt
            registry = 'pypi'
            list_format = 'requirements.txt'
            all_dependencies = parse.requirements_txt(
                files['requirements-txt'],
            )
        else:
            return await render_template(
                'list_invalid.html',
                error='No files provided',
            )
    except parse.UnknownFormat as e:
        return await render_template(
            'list_invalid.html',
            error=e.args[0],
        )

    # Normalize names
    registry_obj = get_registry(registry)
    if direct_dependencies is not None:
        direct_dependencies = [
            (registry_obj.normalize_name(name), version, depends_on)
            for name, version, depends_on in direct_dependencies
        ]
    if all_dependencies is not None:
        all_dependencies = [
            (registry_obj.normalize_name(name), version, depends_on)
            for name, version, depends_on in all_dependencies
        ]

    if direct_dependencies is None:
        direct_dependency_names = None
    else:
        direct_dependency_names = {
            name
            for name, version, depends_on in direct_dependencies
        }

    # Insert in the database
    with db.begin() as trans:
        list_id, = trans.execute(
            database.dependency_lists.insert()
            .values(
                created=datetime.utcnow(),
                registry=registry,
                format=list_format,
            )
        ).inserted_primary_key
        for dep_name, dep_version, depends_on in all_dependencies:
            if direct_dependency_names is None:
                direct = None  # We don't know
            else:
                direct = dep_name in direct_dependency_names
            depends_on = '#'.join(depends_on)
            trans.execute(
                database.dependency_list_items.insert()
                .values(
                    list_id=list_id,
                    norm_name=dep_name,
                    version=dep_version,
                    direct=direct,
                    depends_on=depends_on,
                )
            )

    return redirect(
        url_for('view_list', list_id=crypto.encode_id(list_id)),
        303,
    )


@app.get('/list/<list_id>')
async def view_list(list_id):
    try:
        list_id = crypto.decode_id(list_id)
    except crypto.InvalidId:
        return await render_template('list_notfound.html'), 404

    # Get packages from the database
    rows = db.execute(
        sqlalchemy.select([
            database.dependency_lists.c.registry,
            database.dependency_list_items.c.norm_name,
            database.packages.c.orig_name,
            database.packages.c.last_refresh,
            database.packages.c.repository,
            database.packages.c.author,
            database.packages.c.description,
            database.packages.c.description_type,
            database.dependency_lists.c.format,
            database.dependency_list_items.c.version,
            database.dependency_list_items.c.direct,
            database.dependency_list_items.c.depends_on,
        ])
        .select_from(
            database.dependency_lists
            .join(
                database.dependency_list_items,
                database.dependency_lists.c.id
                == database.dependency_list_items.c.list_id,
            )
            .outerjoin(
                database.packages,
                and_(
                    database.dependency_list_items.c.norm_name
                    == database.packages.c.norm_name,
                    database.dependency_lists.c.registry
                    == database.packages.c.registry,
                ),
            )
        )
        .where(database.dependency_lists.c.id == list_id)
    )
    registry = list_format = None
    deps = {}
    for row in rows:
        [
            registry, norm_name, orig_name, last_refresh, repository, author,
            description, description_type,
            list_format, version, direct, depends_on,
        ] = row
        if orig_name is None:
            package = None
        else:
            package = Package(
                registry, orig_name, {},
                author=author, description=description,
                description_type=description_type,
                repository=repository,
                last_refresh=last_refresh,
            )
        if depends_on:
            depends_on = depends_on.split('#')
        else:
            depends_on = []
        deps[norm_name] = package, version, direct, depends_on

    if registry is None:
        return await render_template('list_notfound.html'), 404
    registry_obj = get_registry(registry)

    # Fill in versions
    rows = db.execute(
        sqlalchemy.select([
            database.package_versions.c.norm_name,
            database.package_versions.c.version,
            database.package_versions.c.release_date,
            database.package_versions.c.yanked,
        ])
        .select_from(
            database.dependency_list_items
            .join(
                database.package_versions,
                and_(
                    database.package_versions.c.norm_name
                    == database.dependency_list_items.c.norm_name,
                    database.package_versions.c.registry == registry,
                ),
            )
        )
        .where(database.dependency_list_items.c.list_id == list_id)
    )
    for row in rows:
        norm_name, version, release_date, yanked = row
        deps[norm_name][0].versions[version] = PackageVersion(
            version,
            release_date=release_date,
            yanked=bool(yanked),
        )

    # Get missing packages from registry
    if logger.isEnabledFor(logging.INFO):
        missing_packages = sum(1 for d in deps.values() if d[0] is None)
        if missing_packages > 0:
            logger.info(
                '%d packages not in database, getting from registry',
                missing_packages,
            )
    for norm_name, (package, version, direct, depends_on) in deps.items():
        if package is None:
            package = await load_package(registry_obj, norm_name)
            deps[norm_name] = package, version, direct, depends_on

    # TODO: Get statements
    statements = []

    for (
        norm_name,
        (package, required_version, direct, depends_on)
    ) in deps.items():
        # Annotate versions
        annotated = annotate_versions(
            registry_obj,
            package.versions,
            statements,
        )

        # Find the one we want
        version = None
        for annotation in annotated:
            if registry_obj.version_match_specifier(
                annotation.version, required_version,
            ):
                # Grab the first one, they are in reverse order
                version = annotation
                break

        deps[norm_name] = (
            package,
            version,
            required_version,
            direct,
            depends_on,
        )

    # Format as tree if we have some direct and some indirect dependencies
    if (
        any(d[3] is True for d in deps.values())
        and any(d[3] is False for d in deps.values())
    ):
        tree = []

        def render(norm_name, seen):
            # Avoid cycles
            if norm_name in seen:
                return
            seen = set(seen)
            seen.add(norm_name)

            (
                package,
                version,
                required_version,
                direct,
                depends_on,
            ) = deps[norm_name]
            return (
                package,
                version,
                required_version,
                [render(n, seen) for n in depends_on],
            )

        for norm_name, (package, version, required_version, direct, depends_on) in sorted(
            deps.items(),
            key=lambda p: p[0],
        ):
            if direct is True:
                tree.append(render(norm_name, set()))

        return await render_template(
            'list_tree.html',
            registry=registry,
            format=list_format,
            dependencies=tree,
        )
    else:
        return await render_template(
            'list.html',
            registry=registry,
            format=list_format,
            dependencies=[
                p[1]
                for p in sorted(deps.items(), key=lambda p: p[0])
            ],
        )


async def get_package(registry_obj, norm_name):
    # Get from database
    package = db.execute(
        sqlalchemy.select([
            database.packages.c.orig_name,
            database.packages.c.last_refresh,
            database.packages.c.repository,
            database.packages.c.author,
            database.packages.c.description,
            database.packages.c.description_type,
        ])
        .select_from(database.packages)
        .where(
            database.packages.c.registry == registry_obj.NAME,
            database.packages.c.norm_name == norm_name,
        )
        .limit(1)
    ).first()

    # If not in database, load from registry API
    if not package:
        return await load_package(registry_obj, norm_name)

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
            database.package_versions.c.version,
            database.package_versions.c.release_date,
            database.package_versions.c.yanked,
        ])
        .select_from(database.package_versions)
        .where(
            database.package_versions.c.registry == registry_obj.NAME,
            database.package_versions.c.norm_name == norm_name,
        )
        .order_by(desc(database.package_versions.c.release_date))
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
        registry_obj.NAME,
        orig_name,
        versions,
        author=author,
        description=description,
        description_type=description_type,
        repository=repository,
        last_refresh=last_refresh,
    )

    # If too old, refresh
    if datetime.utcnow() - package.last_refresh > MAX_AGE:
        package = await refresh_package(registry_obj, package)

    return package


async def load_package(registry_obj, norm_name):
    logger.info(
        "Loading package %r / %r...",
        registry_obj.NAME,
        norm_name,
    )

    async with aiohttp.ClientSession() as http:
        package = await registry_obj.get_package(norm_name, http)

    with db.begin() as trans:
        trans.execute(
            database.packages.insert()
            .values(
                registry=registry_obj.NAME,
                norm_name=norm_name,
                last_refresh=package.last_refresh,
                orig_name=package.orig_name,
                author=package.author,
                description=package.description,
                description_type=package.description_type,
                repository=package.repository,
            )
        )

        for num, version in package.versions.items():
            trans.execute(
                database.package_versions.insert()
                .values(
                    registry=registry_obj.NAME,
                    norm_name=registry_obj.normalize_name(package.orig_name),
                    version=num,
                    release_date=version.release_date,
                    yanked=bool(version.yanked),
                )
            )

    return package


async def refresh_package(registry_obj, old_package):
    logger.info(
        "Refreshing package %r / %r...",
        registry_obj.NAME,
        old_package.orig_name,
    )

    norm_name = registry_obj.normalize_name(old_package.orig_name)

    async with aiohttp.ClientSession() as http:
        new_package = await registry_obj.get_package(norm_name, http)

    with db.begin() as trans:
        # Update package data
        update = {'last_refresh': new_package.last_refresh}
        if new_package.orig_name != old_package.orig_name:
            update['orig_name'] = new_package.orig_name
        if new_package.author != old_package.author:
            update['author'] = new_package.author
        if new_package.description != old_package.description:
            update['description'] = new_package.description
        if new_package.description_type != old_package.description_type:
            update['description_type'] = new_package.description_type
        if new_package.repository != old_package.repository:
            update['repository'] = new_package.repository
        trans.execute(
            database.packages.update()
            .values(**update)
            .where(
                database.packages.c.registry == registry_obj.NAME,
                database.packages.c.norm_name == norm_name,
            )
        )

        # Update versions
        for num, version in new_package.versions.items():
            if num not in old_package.versions:
                trans.execute(
                    database.package_versions.insert()
                    .values(
                        registry=registry_obj.NAME,
                        norm_name=norm_name,
                        version=num,
                        release_date=version.release_date,
                        yanked=bool(version.yanked),
                    )
                )

    return new_package
