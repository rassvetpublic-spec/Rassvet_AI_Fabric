import os
import unittest
from raif_ag_supervisor.session_probe import parse_tasklist, running_components, windows_process_start_marker


class ProcessProbeTests(unittest.TestCase):
    def test_parse_csv_no_headers(self):
        output = (
            '"Antigravity.exe","100","Console","1","10,000 K"\n'
            '"language_server.exe","200","Console","1","3,000 K"\n'
            '"agy.exe","300","Console","1","1,000 K"\n'
            '"unrelated.exe","400","Console","1","3,000 K"\n'
        )
        result = parse_tasklist(output)
        self.assertEqual(len(result), 3)
        self.assertEqual({p.pid for p in result}, {100, 200, 300})

    def test_invalid_pid_and_duplicates(self):
        output = (
            '"Antigravity.exe","0"\n'
            '"Antigravity.exe","notpid"\n'
            '"Antigravity.exe","123"\n'
            '"Antigravity.exe","123"\n'
        )
        result = parse_tasklist(output)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].pid, 123)

    def test_process_snapshot_contains_no_secrets(self):
        result = parse_tasklist('"Antigravity.exe","42"\n')
        self.assertEqual(result[0].image_name, "antigravity.exe")
        self.assertFalse(hasattr(result[0], "token"))

    def test_invalid_process_marker_is_unavailable(self):
        self.assertIsNone(windows_process_start_marker(-1))

    @unittest.skipUnless(os.name == "nt", "Windows-only native process times")
    def test_current_process_has_creation_marker(self):
        marker = windows_process_start_marker(os.getpid())
        self.assertIsInstance(marker, str)
        self.assertGreater(int(marker, 16), 0)
        self.assertEqual(windows_process_start_marker(os.getpid()), marker)

    @unittest.skipUnless(os.name == "nt", "Windows-only process discovery")
    def test_live_probe_is_read_only(self):
        result = running_components()
        self.assertIsInstance(result, tuple)


if __name__ == "__main__":
    unittest.main()
