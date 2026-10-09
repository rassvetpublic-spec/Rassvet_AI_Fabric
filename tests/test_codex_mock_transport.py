"""Интеграционные тесты офлайн-транспорта; отдельный процесс, ноль моделей."""
import os
import time
import unittest
from unittest.mock import patch

from rai_fabric.codex_mock_transport import _safe_mock_environment, run_codex_mock
from rai_fabric.codex_protocol import CodexProtocolError


class CodexMockTransportTests(unittest.TestCase):
    def test_successful_mock_subprocess(self):
        result = run_codex_mock(scenario="success")
        self.assertEqual(result["state"], "COMPLETE")
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["response"], "Подставной ответ получен")
        self.assertEqual(result["thread_id"], "mock-thread")
        self.assertEqual(result["turn_id"], "mock-turn")

    def test_failed_turn_does_not_count_as_success(self):
        r = run_codex_mock(scenario="failed")
        self.assertEqual(r["verdict"], "BLOCKED")
        self.assertEqual(r["cursor"], "VERIFY_EXTERNAL_SIDE_EFFECTS")

    def test_approval_request_is_not_automatically_accepted(self):
        start = time.monotonic()
        r = run_codex_mock(scenario="approval", timeout_seconds=2)
        self.assertEqual(r["verdict"], "BLOCKED")
        self.assertEqual(r["cursor"], "MANUAL_SERVER_REQUEST")
        self.assertLess(time.monotonic()-start, 5)

    def test_timeout_fails_closed_and_terminates_child(self):
        start = time.monotonic()
        r = run_codex_mock(scenario="timeout", timeout_seconds=0.45)
        self.assertEqual(r["verdict"], "BLOCKED")
        self.assertEqual(r["error_code"], "PROCESS_TIMEOUT")
        self.assertLess(time.monotonic()-start, 4)

    def test_eof_without_completed_event_is_not_success(self):
        r = run_codex_mock(scenario="eof")
        self.assertEqual(r["verdict"], "BLOCKED")
        self.assertEqual(r["error_code"], "PROCESS_EOF")

    def test_invalid_scenario_is_rejected_before_start(self):
        with self.assertRaises(CodexProtocolError):
            run_codex_mock(scenario="real-codex")
        with self.assertRaises(CodexProtocolError):
            run_codex_mock(timeout_seconds=-1)

    def test_child_environment_excludes_model_tokens(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "private", "GEMINI_API_KEY": "private",
                                     "ACCESS_TOKEN": "private", "ANTHROPIC_API_KEY": "private",
                                     "GH_TOKEN": "private", "RAI_LEASE_TOKEN": "private"}):
            env = _safe_mock_environment()
        for field in ("OPENAI_API_KEY", "GEMINI_API_KEY", "ACCESS_TOKEN",
                      "ANTHROPIC_API_KEY", "GH_TOKEN", "RAI_LEASE_TOKEN"):
            self.assertNotIn(field, env)
        self.assertNotIn("PYTHONPATH", env)
        self.assertNotIn("USERPROFILE", env)
        self.assertNotIn("HOME", env)


if __name__ == "__main__":
    unittest.main()
