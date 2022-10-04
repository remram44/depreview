import aiohttp
from datetime import datetime, timedelta
from distutils.version import LooseVersion
import logging
import markdown
from markupsafe import Markup
import os
from quart import Quart, render_template, redirect, url_for
import sqlalchemy
from sqlalchemy import desc

from .. import database
from ..registries import get_registry


logger = logging.getLogger(__name__)


MAX_AGE = timedelta(hours=6)


app = Quart(__name__)


db = database.connect(os.environ['DATABASE_URL'])


def render_description(description, description_type):
    if description_type == 'text/markdown':
        return markdown.markdown(description)
    elif description_type == 'text/x-rst':
        pass  # TODO

    return '<pre>%s</pre>' % (
        description.replace('&', '&amp;').replace('<', '&lt;')
    )


@app.route('/')
async def index():
    latest_changes = db.execute(
        sqlalchemy.select([
            database.reviews.c.created,
            database.reviews.c.registry,
            database.reviews.c.name,
            database.reviews.c.type,
            database.reviews.c.proof,
            database.reviews.c.user_id,
            database.users.c.login,
            database.users.c.name,
        ])
        .select_from(
            database.reviews
            .join(
                database.users,
                database.reviews.c.user_id == database.users.c.id,
            )
        )
        .order_by(desc(database.reviews.c.created))
        .limit(10)
    )
    return await render_template(
        'index.html',
        latest_changes=latest_changes,
    )


@app.route('/p/<registry>/<name>')
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
    package, last_refresh = database.get_package(db, registry, name)

    # If too old, refresh
    if datetime.utcnow() - last_refresh > MAX_AGE:
        package = await refresh_package(registry_obj, package)
        last_refresh = None

    # Annotate versions with whether they are outdated
    versions = annotate_versions(package.versions)

    return await render_template(
        'package.html',
        package=package,
        versions=versions,
        rendered_description=Markup(render_description(
            package.description,
            package.description_type,
        )),
        last_refresh=last_refresh,
    )


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
        update = {'last_refresh': datetime.utcnow()}
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


def annotate_versions(versions):
    versions = sorted(
        versions.values(),
        key=lambda v: LooseVersion(v.version),
        reverse=True,
    )
    # TODO
    return versions


def main():
    app.run()
