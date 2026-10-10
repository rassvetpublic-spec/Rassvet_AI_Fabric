"""Одна разрешённая модельная задача, без настоящих сетевых вызовов."""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from rai_fabric.codex_live_executor import (
    _safe_env, _parse_generated_code, _drive_single_turn, _validate_workspace,
    run_live_task, SafeProtocolError, _test_generated)
from rai_fabric.store import FabricStore, FabricError

FAKE=Path(__file__).with_name('fake_codex_live_server.py')


class LiveTransportTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name);self.work=root/'workspace';self.work.mkdir()
        self.home=root/'rassvet_ai_fabric';self.home.mkdir()
        self.env=_safe_env(self.home)
        self.cmd=[sys.executable,'-I',str(FAKE)]

    def drive(self,scenario='success',timeout=30,monitor=None):
        return _drive_single_turn([*self.cmd,scenario],self.work,self.env,
                                  timeout_seconds=timeout,monitor=monitor)

    def test_one_turn_completed_synthetic(self):
        r=self.drive()
        self.assertEqual(r['status'],'PASS_WITH_SCOPE')
        self.assertEqual(r['methods_sent'],['initialize','initialized','thread/start','turn/start'])
        self.assertEqual(r['code'],'ONE_TURN_COMPLETED')
        self.assertEqual(r['cleanup'],'GRACEFUL_OR_EXITED')
        self.assertNotIn('secret',str(r))
        self.assertEqual(_parse_generated_code(r['_private_reply']),
                         'def add(a, b):\n    return a + b\n')

    def test_rpc_error_redacted(self):
        r=self.drive('turn_rpc_error')
        self.assertEqual(r['code'],'RPC_SERVER_ERROR')
        self.assertEqual(r.get('rpc_error_code'),-32001)
        self.assertNotIn('Bearer secret',str(r))

    def test_unexpected_server_request(self):
        r=self.drive('server_request')
        self.assertEqual(r['code'],'SERVER_APPROVAL_REQUIRED')
        self.assertNotIn('accept',r['methods_sent'])

    def test_tool_activity_is_blocked(self):
        r=self.drive('tool_started')
        self.assertEqual(r['code'],'TOOL_EXECUTION_BLOCKED')
        self.assertTrue(r['tool_actions_seen'])

    def test_wrong_turn_is_blocked(self):
        self.assertEqual(self.drive('wrong_turn')['code'],'WRONG_TURN_ID')

    def test_failed_turn_never_passes(self):
        self.assertEqual(self.drive('failed')['code'],'TURN_NOT_COMPLETED')

    def test_cancel_before_response(self):
        self.assertEqual(self.drive(monitor=lambda:False)['code'],'CANCELLED_OR_LEASE_LOST')

    def test_json_rejects_duplicate_keys_and_executables(self):
        for text in ('{"source":"x","source":"y"}',
                     '{"source":"import os\\n"}',
                     '{"source":"def add(a,b):\\n    __import__(\\"os\\")\\n"}',
                     '{"source":"def add(a,b):\\n    return a * b\\n"}'):
            with self.subTest(text=text),self.assertRaises(SafeProtocolError):
                _parse_generated_code(text)

    def test_code_is_run_locally_only_after_validation(self):
        src=_parse_generated_code('{"source":"def add(a,b):\\n    return a + b\\n"}')
        results=_test_generated(self.work,src)
        self.assertTrue(results['passed'])
        self.assertEqual(results['local_test_count'],3)
        with self.assertRaises(SafeProtocolError):_test_generated(self.work,src)

    def test_no_api_key_env_inherited(self):
        os.environ['OPENAI_API_KEY']='secret-123'
        try:
            self.assertNotIn('OPENAI_API_KEY',_safe_env(self.home))
        finally:
            del os.environ['OPENAI_API_KEY']


class QueueLiveTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name);self.work=root/'workspace';self.work.mkdir()
        self.home=root/'rassvet_ai_fabric';self.home.mkdir()
        self.exe=root/'codex.exe';self.exe.write_bytes(b'fake')
        self.digest=hashlib.sha256(self.exe.read_bytes()).hexdigest()
        self.db=FabricStore(root/'task.sqlite',initialize=True);self.addCleanup(self.db.close)
        self.db.submit('safe one-turn','codex-app',str(self.work),task_id='exact-task')

    def perform(self,*,consent=True,driver=None,task_id='exact-task'):
        if driver is None:
            def driver(*args,**kw):
                return {'status':'PASS_WITH_SCOPE','code':'ONE_TURN_COMPLETED',
                    'methods_sent':['initialize','initialized','thread/start','turn/start'],
                    'turn_started':True,'turn_completed':True,'cleanup':'GRACEFUL_OR_EXITED',
                    '_private_reply':'{"source":"def add(a,b):\\n    return a + b\\n"}'}
        return run_live_task(self.db,task_id=task_id,binary=self.exe,
                             codex_home=self.home,workspace=self.work,
                             expected_binary_sha256=self.digest,
                             one_turn_consent=consent,driver=driver)

    def test_single_real_task_and_checkpoint(self):
        result=self.perform()
        self.assertEqual(result['status'],'COMPLETE')
        self.assertEqual(self.db.get('exact-task')['attempt'],1)
        self.assertTrue((self.work/'arithmetic.py').exists())
        self.assertEqual(result['checkpoint']['evidence']['local_test_count'],3)
        self.assertFalse(result['checkpoint']['evidence']['simulation'])
        self.assertNotIn('lease_token',str(result))

    def test_no_consent_fails_before_claim(self):
        with self.assertRaises(FabricError):self.perform(consent=False)
        self.assertEqual(self.db.get('exact-task')['status'],'QUEUED')

    def test_cannot_claim_another_task(self):
        with self.assertRaises(FabricError):self.perform(task_id='other')
        self.assertEqual(self.db.get('exact-task')['attempt'],0)

    def test_binary_hash_mismatch_before_claim(self):
        self.exe.write_bytes(b'drift')
        with self.assertRaises(SafeProtocolError):self.perform()
        self.assertEqual(self.db.get('exact-task')['status'],'QUEUED')

    def test_blocked_real_task_is_not_retried(self):
        def fails(*args,**kwargs):return {'status':'BLOCKED','code':'RPC_SERVER_ERROR',
                                         'turn_started':False,'turn_completed':False,'cleanup':'GRACEFUL_OR_EXITED'}
        result=self.perform(driver=fails)
        self.assertEqual(result['status'],'BLOCKED')
        self.assertEqual(self.db.get('exact-task')['attempt'],1)
        with self.assertRaises(FabricError):self.perform(driver=fails)

    def test_workspace_must_be_empty(self):
        (self.work/'existing.txt').write_text('x')
        with self.assertRaises(SafeProtocolError):self.perform()
        self.assertEqual(self.db.get('exact-task')['status'],'QUEUED')

    def test_claim_specific_task_does_not_claim_other(self):
        self.db.submit('other objective','codex-app',str(self.work),task_id='aaa')
        result=self.db.claim('test',provider='codex-app',task_id='exact-task')
        self.assertEqual(result['task_id'],'exact-task')
        self.assertEqual(self.db.get('aaa')['status'],'QUEUED')

    def test_blocked_payload_does_not_leak_model_reply(self):
        def bad(*args,**kw):return {'status':'PASS_WITH_SCOPE','code':'ONE_TURN_COMPLETED',
                                    'turn_started':True,'turn_completed':True,
                                    '_private_reply':'{"source":"import os\\n"}'}
        r=self.perform(driver=bad)
        self.assertEqual(r['status'],'BLOCKED')
        self.assertNotIn('import os',str(self.db.events('exact-task')))


if __name__=='__main__':unittest.main()
