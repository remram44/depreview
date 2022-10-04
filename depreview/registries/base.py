class BaseRegistry(object):
    async def get_package(self, name, http):
        raise NotImplementedError

    def normalize_name(self, name):
        raise NotImplementedError


class Package(object):
    def __init__(self, name, versions, *, author, description, description_type, repository):
        self.name = name
        self.versions = versions
        self.author = author
        self.description = description
        self.description_type = description_type
        self.repository = repository

    def __repr__(self):
        return '<Package %r>' % self.name


class PackageVersion(object):
    def __init__(self, version, *, release_date, yanked):
        self.version = version
        self.release_date = release_date
        self.yanked = yanked

    def __repr__(self):
        return '<PackageVersion %r %s%s>' % (
            self.version,
            self.release_date.date().isoformat(),
            ' yanked' if self.yanked else '',
        )
