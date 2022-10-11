import re
import tomli

from .registries.python_pypi import PythonPyPI


class UnknownFormat(ValueError):
    """The file is not in a format we recognize.
    """


def poetry_lock(list_file):
    try:
        data = tomli.load(list_file)
    except tomli.TOMLDecodeError:
        raise UnknownFormat('Invalid TOML')
    try:
        packages = []
        for package in data['package']:
            # Get package name and version
            if (
                not isinstance(package['name'], str)
                or 'version' not in package
            ):
                raise UnknownFormat('Invalid lock file')
            elif not isinstance(package['version'], str):
                raise UnknownFormat('Invalid lock file')

            # Get dependencies
            dependencies = []
            if package.get('dependencies'):
                if not isinstance(package['dependencies'], dict):
                    raise UnknownFormat('Invalid lock file')
                for name, version in package['dependencies'].items():
                    if not isinstance(name, str):
                        raise UnknownFormat('Invalid lock file')
                    dependencies.append(PythonPyPI.normalize_name(name))
            # TODO: Support extras

            packages.append((
                PythonPyPI.normalize_name(package['name']),
                '==' + package['version'],
                sorted(dependencies),
            ))
        return packages
    except KeyError:
        raise UnknownFormat('Invalid lock file')


def next_major(version):
    major, rest = re.match(r'^([0-9]+)(.*)$', version).groups()
    major = int(major, 10)
    return f'{major + 1}.0.0'


def next_minor(version):
    major, minor, rest = re.match(
        r'^([0-9]+\.)([0-9]+)(.*)$',
        version,
    ).groups()
    minor = int(minor, 10)
    return f'{major}{minor + 1}.0'


def poetry_to_standard_spec(spec):
    result = []
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        if part == '*':
            return ''
        if part.startswith('^'):
            part = part[1:]
            result.append('>=' + part)
            result.append('<' + next_major(part))
        elif part.startswith('~'):
            part = part[1:]
            result.append('>=' + part)
            result.append('<' + next_minor(part))
        elif part.startswith('='):
            part = part[1:]
            result.append('==' + part)
        elif part.startswith(('>', '<')):
            result.append(part)
        else:
            result.append('==' + part)
    return ','.join(result)


def pyproject_toml(list_file):
    try:
        data = tomli.load(list_file)
    except tomli.TOMLDecodeError:
        raise UnknownFormat('Invalid TOML')
    try:
        packages = []
        if not isinstance(data['tool']['poetry']['dependencies'], dict):
            raise UnknownFormat('Invalid Poetry project file')

        def add_list(pkgs):
            for orig_name, version in pkgs.items():
                if (
                    not isinstance(orig_name, str)
                    or not isinstance(version, str)
                ):
                    raise UnknownFormat('Invalid Poetry project file')
                if orig_name.lower() == 'python':
                    # Doesn't count
                    continue
                norm_name = PythonPyPI.normalize_name(orig_name)
                packages.append((
                    norm_name,
                    poetry_to_standard_spec(version),
                    None,
                ))

        add_list(data['tool']['poetry']['dependencies'])
        if data['tool']['poetry'].get('dev-dependencies'):
            add_list(data['tool']['poetry']['dev-dependencies'])
        return packages
    except KeyError:
        raise UnknownFormat('Invalid lock file')


def requirements_txt(list_file):
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
                    PythonPyPI.normalize_name(m.group(1).decode('ascii')),
                    '==' + m.group(2).decode('ascii'),
                    None,
                ))
            if line[-1:] == b'\\':
                escaped = True
        return packages
    except UnicodeDecodeError:
        raise UnknownFormat("Invalid characters in file")
