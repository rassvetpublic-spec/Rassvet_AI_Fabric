"""Не допускать ошибок секций pyproject при установке security-зависимостей."""
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PackageMetadataTests(unittest.TestCase):
    def test_license_is_part_of_project_not_security_extras(self):
        spec = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
        self.assertIn('license', spec['project'])
        self.assertNotIn('license', spec['project']['optional-dependencies'])

    def test_optional_security_is_array_of_requirements(self):
        spec = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
        extras = spec['project']['optional-dependencies']
        self.assertEqual(len(extras['security']), 1)
        self.assertIn('PyJWT[crypto]', extras['security'][0])


if __name__ == '__main__':
    unittest.main()
