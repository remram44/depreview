import pkg_resources


_registries = {}


def get_registry(registry):
    try:
        return _registries[registry]
    except KeyError:
        pass

    for entry in pkg_resources.iter_entry_points('depreview.registries'):
        if entry.name == registry:
            cls = entry.load()
            break
    else:
        return None

    _registries[registry] = obj = cls()
    assert obj.NAME == registry
    return obj
