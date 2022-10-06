import base64
import binascii
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
import hashlib
import os
import struct


class InvalidId(ValueError):
    """Invalid format for encoded ID.
    """


KEY = hashlib.sha256(os.environ['SECRET_KEY'].encode('utf-8')).digest()[:8]


def encode_id(num, key=None):
    if key is None:
        key = KEY
    cipher = Cipher(algorithms.TripleDES(key), modes.ECB())

    # To bytes
    block = struct.pack('>Q', num)
    # Encrypt
    block = cipher.encryptor().update(block)
    # Base64 encode
    return base64.urlsafe_b64encode(block).decode('ascii')[0:11]


def decode_id(encoded, key=None):
    if key is None:
        key = KEY
    cipher = Cipher(algorithms.TripleDES(key), modes.ECB())

    # Base64 decode
    if len(encoded) != 11:
        raise InvalidId
    try:
        block = base64.urlsafe_b64decode(encoded + '=')
    except binascii.Error:
        raise InvalidId
    # Our input is padded, check that the padding is 0 by round-tripping
    b64roundtrip = base64.urlsafe_b64encode(block).decode('ascii')
    if b64roundtrip != encoded + '=':
        raise InvalidId
    # Decrypt
    block = cipher.decryptor().update(block)
    # To number
    return struct.unpack('>Q', block)[0]
