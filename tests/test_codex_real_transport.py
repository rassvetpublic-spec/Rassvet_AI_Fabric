"""Негативные контракты Codex App Server без реальной модели и OAuth."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from rai_fabric.codex_real_transport import _drive_app_server,_environment,_parse_response,SafeProtocolError,probe_installed_codex

FAKE=Path(__file__).with_name('fake_codex_app_server.py')

class RealTransportTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name)
  self.env=_environment(str(self.root/'isolated-home'))
  self.env['RAIF_ASSERT_NO_AUTH']='1'

 def run_server(self, scenario='success', mode='thread', timeout=6):
  return _drive_app_server(command=[sys.executable,'-I',str(FAKE),scenario],
                           cwd=str(self.root),mode=mode,timeout_seconds=timeout,env=self.env)

 def test_thread_no_inference(self):
  r=self.run_server()
  self.assertEqual(r['status'],'PASS_WITH_SCOPE')
  self.assertTrue(r['thread_created'])
  self.assertEqual(r['method_names_sent'],['initialize','initialized','thread/start'])
  self.assertTrue(r['no_turn_start_sent'])
  self.assertEqual(len(r['thread_id_sha256_prefix']),16)
  self.assertEqual(r['child_cleanup'],'GRACEFUL_OR_EXITED')

 def test_initialize_only(self):
  r=self.run_server(scenario='init_only',mode='initialize')
  self.assertEqual(r['status'],'PASS_WITH_SCOPE')
  self.assertFalse(r['thread_created'])

 def test_wrong_rpc_id_fails_closed(self):
  self.assertEqual(self.run_server('wrong_id')['code'],'UNEXPECTED_RPC_ID')

 def test_duplicate_field_fails_closed(self):
  self.assertEqual(self.run_server('duplicate')['code'],'DUPLICATE_JSON_KEY')

 def test_invalid_json_fails_closed(self):
  self.assertEqual(self.run_server('bad_json')['code'],'INVALID_JSONL_FRAME')

 def test_rpc_error_not_exposed(self):
  text=str(self.run_server('rpc_error'))
  self.assertIn('RPC_ERROR_FROM_SERVER',text)
  self.assertNotIn('sensitive diagnostic',text)

 def test_oversize_blocked(self):
  self.assertEqual(self.run_server('oversize')['code'],'OVERSIZED_OR_PARTIAL_FRAME')

 def test_approval_request_blocked(self):
  self.assertEqual(self.run_server('approval')['code'],'SERVER_REQUEST_REQUIRES_MANUAL_HANDLING')

 def test_missing_thread_id(self):
  self.assertEqual(self.run_server('missing_thread')['code'],'THREAD_ID_MISSING_OR_INVALID')

 def test_timeout_bounded(self):
  r=self.run_server('timeout',timeout=1.0)
  self.assertEqual(r['code'],'RPC_TIMEOUT')
  self.assertIn(r['child_cleanup'],('FORCED_OWN_CHILD','FORCED_OWN_CHILD_TREE','GRACEFUL_OR_EXITED'))

 def test_eof_blocked(self):
  self.assertEqual(self.run_server('eof')['code'],'CHILD_STDOUT_EOF')

 def test_binary_allowlist(self):
  with self.assertRaises(SafeProtocolError) as e:
   probe_installed_codex(binary=sys.executable,workspace=self.root)
  self.assertEqual(e.exception.code,'CODEX_EXECUTABLE_NOT_ALLOWLISTED')

 def test_bad_workspace_blocked(self):
  with self.assertRaises(SafeProtocolError) as e:
   _drive_app_server(command=[sys.executable],cwd=str(self.root/'notexist'),mode='thread',timeout_seconds=3,env=self.env)
  self.assertEqual(e.exception.code,'BAD_WORKSPACE')

 def test_error_with_missing_auth_env(self):
  env=_environment(str(self.root/'home'))
  self.assertFalse(any(k in env for k in ('OPENAI_API_KEY','ACCESS_TOKEN','RAI_LEASE_TOKEN','GITHUB_TOKEN')))

 def test_boolean_id_not_accepted(self):
  self.assertEqual(self.run_server('bool_id')['code'], 'UNEXPECTED_RPC_ID')

if __name__=='__main__':unittest.main()
