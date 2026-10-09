# Проверки политики экономии ресурсов GitHub Actions.
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "windows-readonly.yml"


class BudgetCiTests(unittest.TestCase):
    def test_only_windows_runners_in_main_workflows(self):
        for item in (ROOT / ".github" / "workflows").glob("*.yml"):
            content = item.read_text(encoding="utf-8")
            for line in content.splitlines():
                if line.strip().startswith("runs-on:"):
                    self.assertIn("windows-", line, f"Обнаружен не-Windows runner: {item}")

    def test_automatic_runs_are_bounded(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("paths:", content)
        self.assertIn("src/**", content)
        self.assertIn("tests/**", content)
        self.assertIn("workflow_dispatch:", content)
        self.assertNotIn("matrix:", content)
        self.assertIn("cancel-in-progress: true", content)
        self.assertIn("timeout-minutes: 12", content)

    def test_project_policy_is_in_russian(self):
        content = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Windows-only CI", content)
        self.assertIn("не запускать CI на каждом commit", content)


if __name__ == "__main__":
    unittest.main()
