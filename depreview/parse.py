import re

import tomli


class UnknownFormat(ValueError):
    """The file is not in a format we recognize.
    """


def parse_package_list(list_file):
    try:
        data = tomli.load(list_file)
    except tomli.TOMLDecodeError:
        list_file.seek(0, 0)
    else:
        list_file.seek(0, 0)
        if (
            data.keys() == {'package', 'metadata'}
            and data['metadata'].get('files')
        ):
            return 'pypi', 'poetry.lock', parse_poetry_lock(data)
        elif data.get('tool', {}).get('poetry'):
            raise UnknownFormat(
                "Please upload poetry.lock instead of pyproject.toml",
            )
        else:
            raise UnknownFormat("Unrecognized TOML file")

    all_match = True
    matches = 0
    escaped = False
    for line in iter(list_file.readline, b''):
        was_escaped, escaped = escaped, False
        line_strip = line.strip()
        if not line_strip or line_strip[0:1] == b'#':
            continue

        escaped = line_strip[-1:] == b'\\'

        if was_escaped:
            pass
        elif re.match(
            br'^[a-z0-9_-]{1,50}==[a-z0-9-.]{1,20}(?:\s*(?:\\|--|;|#).+)?\s*$',
            line,
        ):
            matches += 1
        else:
            all_match = False
    list_file.seek(0, 0)
    if all_match and matches >= 3:
        return 'pypi', 'requirements.txt', parse_requirements_txt(list_file)

    raise UnknownFormat("Unknown file format")


def parse_poetry_lock(data):
    packages = []
    for package in data['package']:
        packages.append((package['name'], package['version']))
    return packages


def parse_requirements_txt(list_file):
    try:
        packages = []
        escaped = False
        for line in iter(list_file.readline, b''):
            was_escaped, escaped = escaped, False
            line = line.strip()
            if not line or line[0:1] == b'#':
                continue
            if not was_escaped:
                m = re.match(br'([^ =<>]+)==([^ #]+)', line)
                packages.append((
                    m.group(1).decode('ascii'),
                    m.group(2).decode('ascii'),
                ))
            if line[-1:] == b'\\':
                escaped = True
        return packages
    except UnicodeDecodeError:
        raise UnknownFormat("Invalid characters in file")
