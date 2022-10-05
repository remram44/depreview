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

from .. import database
from ..decision import annotate_versions
from ..registries import get_registry, get_all_registry_names


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


MAX_AGE = timedelta(hours=6)


app = Quart(__name__)


db = database.connect(os.environ['DATABASE_URL'])


def clean_html(html):
    return bleach.clean(
        html,
        tags=[
            'p', 'br', 'a', 'img',
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

    # Get from database
    package = database.get_package(db, registry, name)

    # If too old, refresh
    if package is None:
        package = await load_package(registry_obj, name)
    elif datetime.utcnow() - package.last_refresh > MAX_AGE:
        package = await refresh_package(registry_obj, package)

    # Annotate versions with whether they are outdated
    versions = annotate_versions(registry_obj, package.versions)

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
    TODO


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
                database.packages.c.name == old_package['name'],
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
