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
from sqlalchemy import desc

from .. import crypto
from .. import database
from ..decision import annotate_versions
from ..parse import parse_package_list, UnknownFormat
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
            database.statements.c.name,
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
    normalized_name = registry_obj.normalize_name(name)
    if normalized_name != name:
        return redirect(
            url_for('package', registry=registry, name=normalized_name),
            301,
        )

    package = await get_package(registry_obj, name)

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
            database.statements.c.name == normalized_name,
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
        link=registry_obj.get_link(name),
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
    normalized_name = registry_obj.normalize_name(name)

    return redirect(
        url_for('package', registry=registry, name=normalized_name),
        301,
    )


@app.post('/upload-list')
async def upload_list():
    list_file = (await request.files)['list']

    # Parse the file
    try:
        registry, format, deps = parse_package_list(list_file)
    except UnknownFormat as e:
        return await render_template(
            'list_invalid.html',
            error=e.args[0],
        )

    # Normalize names
    registry_obj = get_registry(registry)
    deps = [
        (registry_obj.normalize_name(name), version)
        for name, version in deps
    ]

    # Insert it in the database
    with db.begin() as trans:
        list_id, = trans.execute(
            database.dependency_lists.insert()
            .values(
                created=datetime.utcnow(),
                registry=registry,
                format=format,
            )
        ).inserted_primary_key
        for dep_name, dep_version in deps:
            trans.execute(
                database.dependency_list_items.insert()
                .values(
                    list_id=list_id,
                    name=dep_name,
                    version=dep_version,
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
            database.dependency_list_items.c.name,
            database.packages.c.orig_name,
            database.packages.c.last_refresh,
            database.packages.c.repository,
            database.packages.c.author,
            database.packages.c.description,
            database.packages.c.description_type,
            database.dependency_lists.c.format,
            database.dependency_list_items.c.version,
            database.packages.c.name,
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
                database.dependency_list_items.c.name
                == database.packages.c.name,
                database.dependency_lists.c.registry
                == database.packages.c.registry,
            )
        )
        .where(database.dependency_lists.c.id == list_id)
    )
    registry = format = None
    deps = {}
    for row in rows:
        [
            registry, name, orig_name, last_refresh, repository, author,
            description, description_type,
            format, version, _,
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
        deps[name] = package, version

    if registry is None:
        return await render_template('list_notfound.html'), 404
    registry_obj = get_registry(registry)

    # Fill in versions
    rows = db.execute(
        sqlalchemy.select([
            database.package_versions.c.name,
            database.package_versions.c.version,
            database.package_versions.c.release_date,
            database.package_versions.c.yanked,
        ])
        .select_from(
            database.dependency_list_items
            .join(
                database.package_versions,
                database.package_versions.c.registry == registry,
                database.package_versions.c.name
                == database.dependency_list_items.c.name,
            )
        )
        .where(database.dependency_list_items.c.list_id == list_id)
    )
    for row in rows:
        name, version, release_date, yanked = row
        deps[name][0].versions[version] = PackageVersion(
            version,
            release_date=release_date,
            yanked=bool(yanked),
        )

    # Get missing packages from registry
    if logger.isEnabledFor(logging.INFO):
        missing_packages = sum(1 for pkg, _ in deps.values() if pkg is None)
        if missing_packages > 0:
            logger.info(
                '%d packages not in database, getting from registry',
                missing_packages,
            )
    for name, (package, version) in deps.items():
        if package is None:
            package = await load_package(registry_obj, name)
            deps[name] = package, version

    # TODO: Get statements
    statements = []

    sorted_list = sorted(deps.items(), key=lambda p: p[0])
    deps = []
    for _, (package, required_version) in sorted_list:
        # Annotate versions
        annotated = annotate_versions(
            registry_obj,
            package.versions,
            statements,
        )

        version = None  # Avoids warning
        # Find the one we want
        for annotation in annotated:
            if annotation.version == required_version:
                version = annotation

        deps.append((
            package,
            version,
        ))

    return await render_template(
        'list.html',
        registry=registry,
        format=format,
        deps=deps,
    )


async def get_package(registry_obj, normalized_name):
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
            database.packages.c.name == normalized_name,
        )
        .limit(1)
    ).first()

    # If not in database, load from registry API
    if not package:
        return await load_package(registry_obj, normalized_name)

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
            database.package_versions.c.name == normalized_name,
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


async def load_package(registry_obj, normalized_name):
    logger.info(
        "Loading package %r / %r...",
        registry_obj.NAME,
        normalized_name,
    )

    async with aiohttp.ClientSession() as http:
        package = await registry_obj.get_package(normalized_name, http)

    with db.begin() as trans:
        trans.execute(
            database.packages.insert()
            .values(
                registry=registry_obj.NAME,
                name=normalized_name,
                last_refresh=package.last_refresh,
                orig_name=package.name,
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
                    name=registry_obj.normalize_name(package.name),
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
        old_package.name,
    )

    async with aiohttp.ClientSession() as http:
        new_package = await registry_obj.get_package(old_package.name, http)

    with db.begin() as trans:
        # Update package data
        update = {'last_refresh': new_package.last_refresh}
        if new_package.name != old_package.name:
            update['name'] = new_package.name
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
                database.packages.c.name == old_package.name,
            )
        )

        # Update versions
        for num, version in new_package.versions.items():
            if num not in old_package.versions:
                trans.execute(
                    database.package_versions.insert()
                    .values(
                        registry=registry_obj.NAME,
                        name=registry_obj.normalize_name(new_package.name),
                        version=num,
                        release_date=version.release_date,
                        yanked=bool(version.yanked),
                    )
                )

    return new_package
