"""Проверяем очередь Codex-mock, не позволяя имитации стать настоящим Codex."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rai_fabric.cli import run
from rai_fabric.store import FabricError, FabricStore
from rai_fabric.worker import run_one


class CodexMockQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'state.db'

    def test_codex_mock_in_task_queue_is_marked_simulation(self):
        with FabricStore(self.db, initialize=True) as s:
            s.submit('Имитация анализа проекта', 'codex-mock', str(self.root), task_id='mock-1')
            result = run_one(s, 'codex-mock', timeout_seconds=10)
            self.assertEqual(result['status'], 'COMPLETE')
            checkpoint = result['checkpoint']
            self.assertEqual(checkpoint['verdict'], 'PASS')
            self.assertEqual(checkpoint['cursor'], 'REVIEW_EVIDENCE')
            self.assertTrue(checkpoint['evidence']['simulation'])
            self.assertFalse(checkpoint['evidence']['real_codex'])
            self.assertEqual(checkpoint['evidence']['external_model_calls'], 0)
            self.assertEqual(checkpoint['evidence']['billing'], 'NONE')
            self.assertEqual(s.result('mock-1')['response'], 'Подставной ответ получен')

    def test_real_codex_app_is_still_not_executable(self):
        with FabricStore(self.db, initialize=True) as s:
            s.submit('Реальная задача', 'codex-app', str(self.root), task_id='real-1')
            with self.assertRaises(FabricError):
                run_one(s, 'codex-app', timeout_seconds=10)
            self.assertEqual(s.get('real-1')['status'], 'QUEUED')
            self.assertEqual(s.get('real-1')['checkpoint']['cursor'], 'DISPATCH')

    def test_mock_failure_is_blocked_and_preserves_protocol_cursor(self):
        with FabricStore(self.db, initialize=True) as s:
            s.submit('Имитация отказа', 'codex-mock', str(self.root), task_id='mock-2')
            with patch('rai_fabric.codex_mock_transport.run_codex_mock', return_value={
                    'state': 'BLOCKED', 'verdict': 'BLOCKED', 'cursor': 'VERIFY_PROCESS_EXIT',
                    'response': None, 'error_code': 'PROCESS_EOF'}):
                result = run_one(s, 'codex-mock', timeout_seconds=10)
            self.assertEqual(result['status'], 'BLOCKED')
            self.assertEqual(result['checkpoint']['cursor'], 'VERIFY_PROCESS_EXIT')
            self.assertEqual(result['checkpoint']['evidence']['protocol_error'], 'PROCESS_EOF')
            self.assertTrue(result['checkpoint']['evidence']['simulation'])

    def test_production_task_cannot_depend_on_mock(self):
        with FabricStore(self.db, initialize=True) as s:
            s.submit('Проверка имитатора', 'codex-mock', str(self.root), task_id='fake')
            with self.assertRaises(FabricError):
                s.submit('Реальная задача', 'codex-app', str(self.root),
                         task_id='real', depends_on=['fake'])
            self.assertEqual(len(s.list()), 1)

    def test_cli_mock_task_roundtrip(self):
        run(['--db', str(self.db), 'init'])
        task = run(['--db', str(self.db), 'submit', '--objective', 'Проверить канал без модели',
                    '--provider', 'codex-mock', '--workspace', str(self.root), '--task-id', 'codex-test'])
        self.assertEqual(task['provider'], 'codex-mock')
        result = run(['--db', str(self.db), 'run-once', '--provider', 'codex-mock', '--timeout', '10'])
        self.assertEqual(result['status'], 'COMPLETE')
        self.assertIn('Подставной ответ', run(['--db', str(self.db), 'result', 'codex-test'])['response'])


if __name__ == '__main__':
    unittest.main()
