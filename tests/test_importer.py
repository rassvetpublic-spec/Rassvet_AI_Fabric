import json
import unittest

from raif_ag_supervisor.importer import ImportFormatError, parse_manifest

def manifest(rows):
    return json.dumps(rows).encode("utf-8")

class ImportTests(unittest.TestCase):
    def test_valid(self):
        rows = [{"email": "one@example.test", "refresh_token": "synthetic-a"},
                {"email": "two@example.test", "refresh_token": "synthetic-b"}]
        parsed = parse_manifest(manifest(rows))
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0].email, "one@example.test")

    def test_imported_credential_hidden_from_repr(self):
        record = parse_manifest(manifest([
            {"email": "one@example.test", "refresh_token": "synthetic-internal-secret"}
        ]))[0]
        self.assertNotIn("synthetic-internal-secret", repr(record))

    def test_duplicate_case_insensitive(self):
        with self.assertRaises(ImportFormatError):
            parse_manifest(manifest([
                {"email": "One@example.test", "refresh_token": "synthetic-a"},
                {"email": "one@example.test", "refresh_token": "synthetic-b"}]))

    def test_empty_token_rejected(self):
        with self.assertRaises(ImportFormatError):
            parse_manifest(manifest([{"email": "one@example.test", "refresh_token": ""}]))

    def test_unexpected_field_rejected(self):
        with self.assertRaises(ImportFormatError):
            parse_manifest([{"email":"one@example.test","refresh_token":"synthetic","secret_note":"x"}].__str__().encode())

    def test_missing_field_rejected(self):
        with self.assertRaises(ImportFormatError):
            parse_manifest(manifest([{"email": "one@example.test"}]))

    def test_invalid_json(self):
        with self.assertRaises(ImportFormatError):
            parse_manifest(b"not-json")

    def test_oversize(self):
        with self.assertRaises(ImportFormatError):
            parse_manifest(b" " * (1024 * 1024 + 1))

if __name__ == "__main__":
    unittest.main()
