from datetime import datetime, timedelta
from markupsafe import Markup
import os
from quart import Quart, render_template, redirect, url_for
import sqlalchemy
from sqlalchemy import desc

from .. import database
from ..registries import get_registry, refresh_package


MAX_AGE = timedelta(hours=6)


app = Quart(__name__)


db = database.connect(os.environ['DATABASE_URL'])


def render_description(description, description_type):
    if description_type == 'text/markdown':
        pass  # TODO
    elif description_type == 'text/x-rst':
        pass  # TODO

    return description.replace('&', '&amp;').replace('<', '&lt;')


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
        package = refresh_package(package)
        last_refresh = None

    return await render_template(
        'package.html',
        package=package,
        rendered_description=Markup(render_description(
            package.description,
            package.description_type,
        )),
        last_refresh=last_refresh,
    )


def main():
    app.run()
