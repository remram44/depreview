from datetime import datetime, timedelta
from packaging.version import Version

from .registries.base import PackageVersion


MIN_AGE = timedelta(days=30)
MAX_AGE = timedelta(days=91)  # 4 months


class AnnotatedVersion(PackageVersion):
    def __init__(self, version):
        super(AnnotatedVersion, self).__init__(
            version.version,
            release_date=version.release_date,
            yanked=version.yanked,
        )
        self.status = 'ok'


def _format_count(num, singular, plural=None):
    if plural is None:
        plural = singular + 's'
    if num == 1:
        return f'{num} {singular}'
    else:
        return f'{num} {plural}'


def format_time(td):
    if td.total_seconds() < 60:
        return _format_count(td.total_seconds(), 'second')
    elif td.total_seconds() < 60 * 60:
        minutes = round(td.total_seconds() / (60 * 60))
        return _format_count(minutes, 'minute')
    elif td.total_seconds() < 60 * 60 * 24:
        hours = round(td.total_seconds() / (60 * 60))
        return _format_count(hours, 'hour')
    elif td.total_seconds() < 60 * 60 * 24 * 30:
        days = round(td.total_seconds() / (60 * 60 * 24))
        return _format_count(days, 'day')
    elif td.total_seconds() < 60 * 60 * 24 * 365:
        months = round(td.total_seconds() / (60 * 60 * 24 * 30.4))
        return _format_count(months, 'month')
    else:
        years = round(td.total_seconds() / (60 * 60 * 24 * 365))
        return _format_count(years, 'year')


def annotate_versions(versions):
    versions = sorted(
        versions.values(),
        key=lambda v: Version(v.version),
        reverse=True,
    )

    now = datetime.utcnow()

    annotated = []
    next_version = None
    for version in versions:
        version = AnnotatedVersion(version)

        if version.yanked:
            # Yanked versions should not be used
            version.status = 'yanked', 'yanked'
        elif (
            # The next version has been out for a bit
            next_version is not None
            and next_version.release_date + MIN_AGE < now
        ):
            time = format_time(now - version.release_date)
            msg = f'{time} out of date'
            if version.release_date + MAX_AGE < now:
                version.status = 'very-outdated', msg
            else:
                version.status = 'outdated', msg

        annotated.append(version)

        # We are going in reverse, so the next version is before
        next_version = version

    return annotated
