import pkg_resources


_registries = None


def _load_entrypoints():
    global _registries

    if _registries is None:
        _registries = {}
        for entry in pkg_resources.iter_entry_points('depreview.registries'):
            cls = entry.load()
            assert cls.NAME == entry.name
            _registries[entry.name] = cls()


def get_registry(registry):
    _load_entrypoints()

    try:
        return _registries[registry]
    except KeyError:
        return None


def get_all_registry_names():
    _load_entrypoints()

    return sorted(_registries)
