import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rai_fabric.cli import run
from rai_fabric.store import FabricError, FabricStore
from rai_fabric.worker import run_one


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.state=self.root / 'state.db'

    def test_init_submit_worker_status(self):
        self.assertTrue(run(['--db',str(self.state),'init'])['initialized'])
        task=run(['--db',str(self.state),'submit','--objective','Проверка оркестрации',
                  '--provider','mock','--workspace',str(self.root),'--task-id','fixture'])
        self.assertEqual(task['status'],'QUEUED')
        self.assertEqual(run(['--db',str(self.state),'run-once','--provider','mock'])['status'],'COMPLETE')
        view=run(['--db',str(self.state),'task','fixture'])
        self.assertEqual(view['checkpoint']['cursor'],'REVIEW')

    def test_external_cli_needs_explicit_flag(self):
        run(['--db',str(self.state),'init'])
        run(['--db',str(self.state),'submit','--objective','Без дополнительных расходов','--provider','antigravity',
             '--workspace',str(self.root),'--task-id','fixture'])
        with self.assertRaises(FabricError):
            run(['--db',str(self.state),'run-once','--provider','antigravity'])
        self.assertEqual(run(['--db',str(self.state),'task','fixture'])['status'],'QUEUED')

    def test_windows_batch_runner_blocked_before_claim(self):
        with FabricStore(self.state, initialize=True) as s:
            s.submit('Любой тест', 'antigravity', str(self.root), task_id='fixture')
            with patch('rai_fabric.worker.shutil.which', return_value=r'C:\\tools\\agy.cmd'):
                with self.assertRaises(FabricError):
                    run_one(s,'antigravity',allow_external=True)
            self.assertEqual(s.get('fixture')['status'],'QUEUED')

    def test_mcp_from_real_python_process(self):
        run(['--db',str(self.state),'init'])
        root=Path(__file__).resolve().parents[1]
        env=os.environ.copy()
        env['PYTHONPATH']=str(root/'src')
        payload='\n'.join([json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize',
                                         'params':{'protocolVersion':'2025-11-25'}}),
                           json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'}),
                           json.dumps({'jsonrpc':'2.0','id':2,'method':'tools/list'})])+'\n'
        p=subprocess.run([sys.executable,'-m','rai_fabric','--db',str(self.state),'mcp',
                          '--workspace',str(self.root)],input=payload,capture_output=True,
                         text=True,encoding='utf-8',env=env,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)
        lines=[json.loads(x) for x in p.stdout.splitlines()]
        self.assertEqual(len(lines),2)
        self.assertEqual(lines[-1]['result']['tools'][0]['name'],'rai_health')

if __name__ == '__main__':
    unittest.main()
