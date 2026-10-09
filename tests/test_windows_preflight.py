"""Проверки контрактов нативного Windows CI и безопасной диагностики подписок."""
import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]


class WindowsPreflightTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (_ROOT / relative).read_text(encoding="utf-8")

    def test_windows_ci_has_no_ai_auth_and_is_read_only(self):
        workflow = self.read('.github/workflows/windows-readonly.yml')
        self.assertIn('runs-on: windows-latest', workflow)
        # Обычный push проверяет Python 3.11; 3.13 доступен вручную без CI-матрицы.
        self.assertIn("python_version:", workflow)
        self.assertIn("default: '3.11'", workflow)
        self.assertIn("- '3.13'", workflow)
        self.assertNotIn("matrix:", workflow)
        self.assertIn('contents: read', workflow)
        self.assertIn('persist-credentials: false', workflow)
        for step in ('windows-preflight.ps1', 'run-tests.ps1', 'demo.ps1', 'demo-codex-mock.ps1'):
            self.assertIn(step, workflow)
        for forbidden in ('OPENAI_API_KEY', 'GEMINI_API_KEY', 'curl ', 'Authorization: Bearer',
                          'codex exec', 'agy -p', 'workflow_run'):
            self.assertNotIn(forbidden, workflow)

    def test_preflight_does_not_run_cloud_executables_or_read_secrets(self):
        script = self.read('scripts/windows-preflight.ps1')
        self.assertIn('RAI_FABRIC_WINDOWS_PREFLIGHT/1', script)
        self.assertIn("inference_requests = 0", script)
        self.assertIn("oauth_tokens_read = $false", script)
        self.assertIn("sqlite_database_created = $false", script)
        self.assertIn("'NOT_TESTED'", script)
        self.assertIn('Get-Command', script)
        self.assertNotIn('& codex', script)
        self.assertNotIn('& agy', script)
        self.assertNotIn('Get-Content', script)
        self.assertNotIn('Set-Content', script)
        self.assertNotIn('Invoke-WebRequest', script)

    def test_smoke_creates_only_mock_temp_workspace(self):
        demo = self.read('scripts/demo.ps1')
        self.assertIn('Join-Path $env:TEMP', demo)
        self.assertIn('--provider mock', demo)
        self.assertNotIn('--allow-external', demo)
        self.assertNotIn('codex-app', demo)
        self.assertNotIn('antigravity', demo)
        self.assertIn("'PYTHONPATH', $oldPythonPath, 'Process'", demo)

    def test_windows_scripts_prefer_current_python_and_restore_environment(self):
        script = self.read('scripts/run-tests.ps1')
        self.assertLess(script.find('Get-Command python'), script.find('Get-Command py -ErrorAction'))
        self.assertIn("'PYTHONPATH', $oldPythonPath, 'Process'", script)
        self.assertIn('unittest discover', script)
        self.assertIn('$LASTEXITCODE -ne 0', script)

    def test_subscription_probe_documents_unverified_status(self):
        doc = self.read('docs/WINDOWS_PREFLIGHT.md')
        self.assertIn('NOT_TESTED', doc)
        self.assertIn('Codex App Server', doc)
        self.assertIn('chatgpt.tokens.use.direct', doc)
        self.assertIn('личного компьютера', doc)
        self.assertIn('не читает', doc.lower())


if __name__ == '__main__':
    unittest.main()
