from io import BytesIO
import unittest

from depreview.parse import UnknownFormat, parse_package_list


class TestParse(unittest.TestCase):
    def test_pyproject(self):
        result = parse_package_list(BytesIO(
            b'[tool.poetry]\nname = "depreview"\nversion = "0.1.0"\n\n'
            + b'[tool.poetry.dependencies]\n'
            + b'aiofiles = "^22.1.0"\naiohttp = "*"\n'
            + b'\n[build-system]\nrequires = ["poetry-core"]\n'
            + b'build-backend = "poetry.core.masonry.api"\n'
        ))
        self.assertEqual(
            result,
            (
                'pypi',
                'pyproject.toml',
                [
                    ('aiofiles', '^22.1.0'),
                    ('aiohttp', '*'),
                ]
            )
        )

    def test_poetry_lock(self):
        result = parse_package_list(BytesIO(
            b'[[package]]\nname = "aiofiles"\nversion = "22.1.0"\n\n'
            + b'[[package]]\nname = "aiohttp"\nversion = "3.8.3"\n\n'
            + b'[metadata]\nlock-version = "1.1"\n\n'
            + b'[metadata.files]\naiofiles = []\naiohttp = []\n'
        ))
        self.assertEqual(
            result,
            (
                'pypi',
                'poetry.lock',
                [
                    ('aiofiles', '22.1.0'),
                    ('aiohttp', '3.8.3'),
                ],
            ),
        )

    def test_requirements_txt(self):
        result = parse_package_list(BytesIO(
            b'# Comment here\n'
            + b'aiofiles==22.1.0 ; python_version >= "3.8 \\\n'
            + b'    --hash=secure\n'
            + b'\n'
            + b'aiohttp==3.8.3 --hash=secure\n'
            + b'aiosignal==1.2.0\n'
        ))
        self.assertEqual(
            result,
            (
                'pypi',
                'requirements.txt',
                [
                    ('aiofiles', '22.1.0'),
                    ('aiohttp', '3.8.3'),
                    ('aiosignal', '1.2.0'),
                ]
            )
        )
