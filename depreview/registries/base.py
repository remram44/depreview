from datetime import datetime


class BaseRegistry(object):
    async def get_package(self, name, http):
        raise NotImplementedError

    def normalize_name(self, name):
        raise NotImplementedError

    def get_link(self, name):
        raise NotImplementedError


class Package(object):
    def __init__(
        self,
        registry,
        name,
        versions,
        *,
        author,
        description,
        description_type,
        repository,
        last_refresh=None,
    ):
        self.registry = registry
        self.name = name
        self.versions = versions
        self.author = author
        self.description = description
        self.description_type = description_type
        self.repository = repository
        if last_refresh is None:
            self.last_refresh = datetime.utcnow()
        else:
            self.last_refresh = last_refresh

    def __repr__(self):
        return '<Package %r>' % self.name


class PackageVersion(object):
    def __init__(self, version, *, release_date, yanked):
        self.version = version
        self.release_date = release_date
        self.yanked = yanked

    def __cmp__(self, other):
        raise NotImplementedError

    def __repr__(self):
        return '<PackageVersion %r %s%s>' % (
            self.version,
            self.release_date.date().isoformat() if self.release_date else 'no-date',
            ' yanked' if self.yanked else '',
        )
