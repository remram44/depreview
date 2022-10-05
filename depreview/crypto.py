class InvalidId(ValueError):
    """Invalid format for encoded ID.
    """


def encode_id(num):
    # TODO
    return f'{num:06}'


def decode_id(encoded):
    try:
        return int(encoded, 10)
    except ValueError:
        raise InvalidId
