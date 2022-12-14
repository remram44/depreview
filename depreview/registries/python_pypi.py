from datetime import datetime
import logging
import packaging.specifiers
import packaging.version
import re

from .base import BaseRegistry, Package, PackageVersion


logger = logging.getLogger(__name__)


_repository_url = re.compile(r'^https?://(github.com|gitlab.com|codeberg.org)(?:/.*)?$')


class PythonPyPI(BaseRegistry):
    NAME = 'pypi'

    async def get_package(self, name, http):
        norm_name = self.normalize_name(name)
        async with http.get(f'https://pypi.org/pypi/{norm_name}/json') as resp:
            data = await resp.json()

        orig_name = data['info']['name']
        author = data['info'].get('author')
        description = data['info'].get('description')
        description_type = data['info'].get('description_content_type') or 'text/x-rst'

        # Collect URLs
        urls_lower = {}
        if 'home_page' in data['info']:
            urls_lower['home_page'] = [data['info']['home_page']]
        for k, v in (data['info'].get('project_urls') or {}).items():
            urls_lower.setdefault(k.lower(), []).append(v)

        # Find repository
        repository = None
        for keyword in ('source', 'source code', 'repository'):
            if keyword in urls_lower:
                repository = urls_lower[keyword][0]
                break
        if repository is None and 'home_page' in urls_lower:
            if (
                _repository_url.match(urls_lower['home_page'][0])
                or urls_lower['home_page'][0].endswith('.git')
            ):
                repository = urls_lower['home_page'][0]

        # Go over versions
        def is_version_valid(num):
            try:
                packaging.version.parse(num)
                return True
            except packaging.version.InvalidVersion:
                return False
        versions = {
            k: self._parse_version(k, v)
            for k, v in data['releases'].items()
            if v and is_version_valid(k)
        }

        return Package(
            self.NAME,
            orig_name,
            versions,
            author=author,
            description=description,
            description_type=description_type,
            repository=repository,
        )

    def _parse_version(self, version, data):
        first_date = None
        all_yanked = True
        for build in data:
            date = build['upload_time_iso_8601']
            date = datetime.fromisoformat(date.rstrip('Z'))
            if first_date is None or first_date > date:
                first_date = date
            if not build['yanked']:
                all_yanked = False

        return PackageVersion(
            version,
            release_date=first_date,
            yanked=all_yanked,
        )

    @staticmethod
    def normalize_name(name):
        return name.lower().replace('_', '-')

    def get_link(self, name):
        norm_name = self.normalize_name(name)
        return f'https://pypi.org/project/{norm_name}/'

    def version_comparison_key(self, version):
        return packaging.version.parse(version)

    def is_prerelease(self, version):
        return packaging.version.parse(version).is_prerelease

    def version_match_specifier(self, version, specifier):
        specifier = packaging.specifiers.SpecifierSet(specifier)
        return version in specifier
