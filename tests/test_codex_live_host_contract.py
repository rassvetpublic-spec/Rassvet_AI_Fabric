"""Контракт единичной Windows-передачи: никаких авто-повторов и Linux CI."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
LAUNCH=ROOT/'delivery/windows/Start-RAiF-Codex-Live-10_0.ps1'

class HostContractTests(unittest.TestCase):
    def test_one_time_marker_precedes_live_turn(self):
        s=LAUNCH.read_text(encoding='utf-8-sig')
        self.assertIn('ONE_REAL_TURN_10_0_CONSUMED.json',s)
        self.assertLess(s.index('[IO.FileMode]::CreateNew'),s.index("$argsLive ="))
        self.assertIn('--consent-one-turn',s)
        self.assertIn('ChatGPTLoginStatus',s)

    def test_both_files_in_downloads_and_result_in_project_root(self):
        s=LAUNCH.read_text(encoding='utf-8-sig')
        self.assertIn('C:\\GIT\\Rassvet_AI_Fabric',s)
        self.assertIn('RAiF-Windows-RESULT-CODEX-LIVE-',s)
        self.assertIn('RAiF-Codex-Live-10_0',s)
        self.assertIn('Compress-Archive',s)

    def test_no_full_auth_logs_or_api_key_fallback(self):
        s=LAUNCH.read_text(encoding='utf-8-sig')
        for token in ('OPENAI_API_KEY','CODEX_ACCESS_TOKEN','OPENAI_BASE_URL'):
            self.assertIn(token,s)
        self.assertIn('ChatGPT',s)
        self.assertNotIn('Start-Transcript',s)
        self.assertNotIn('GEMINI_API_KEY=$',s)

if __name__=='__main__':unittest.main()
