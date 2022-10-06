from io import BytesIO
import unittest

from depreview import parse


class TestParse(unittest.TestCase):
    def test_pyproject(self):
        result = parse.pyproject_toml(BytesIO(
            b'[tool.poetry]\nname = "depreview"\nversion = "0.1.0"\n\n'
            + b'[tool.poetry.dependencies]\n'
            + b'aiofiles = "^22.1.2"\naiohttp = "*"\n'
            + b'aiosignal = "=1.2.0"\nattrs = "~22.1.2"\n'
            + b'\n[build-system]\nrequires = ["poetry-core"]\n'
            + b'build-backend = "poetry.core.masonry.api"\n'
        ))
        self.assertEqual(
            result,
            [
                ('aiofiles', '>=22.1.2,<23.0.0', None),
                ('aiohttp', '', None),
                ('aiosignal', '==1.2.0', None),
                ('attrs', '>=22.1.2,<22.2.0', None),
            ],
        )

    def test_poetry_lock(self):
        result = parse.poetry_lock(BytesIO(
            b'[[package]]\nname = "aiofiles"\nversion = "22.1.0"\n\n'
            + b'[[package]]\nname = "aiohttp"\nversion = "3.8.3"\n\n'
            + b'[package.dependencies]\naiosignal = ">=1.1.2"\n'
            + b'[metadata]\nlock-version = "1.1"\n\n'
            + b'[metadata.files]\naiofiles = []\naiohttp = []\n'
        ))
        self.assertEqual(
            result,
            [
                ('aiofiles', '==22.1.0', []),
                ('aiohttp', '==3.8.3', [('aiosignal', '>=1.1.2')]),
            ],
        )

    def test_requirements_txt(self):
        result = parse.requirements_txt(BytesIO(
            b'# Comment here\n'
            + b'aiofiles==22.1.0 ; python_version >= "3.8 \\\n'
            + b'    --hash=secure\n'
            + b'\n'
            + b'aiohttp==3.8.3 --hash=secure\n'
            + b'aiosignal==1.2.0\n'
        ))
        self.assertEqual(
            result,
            [
                ('aiofiles', '==22.1.0', None),
                ('aiohttp', '==3.8.3', None),
                ('aiosignal', '==1.2.0', None),
            ],
        )
