import io
import json
import tempfile
import unittest
from pathlib import Path

from rai_fabric.gateway import Gateway
from rai_fabric.mcp_server import MCPStdioServer
from rai_fabric.store import FabricError, FabricStore


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = FabricStore(self.root / 'state.db', initialize=True)
        self.addCleanup(self.db.close)
        self.gateway = Gateway(self.db, self.root)
        self.s = MCPStdioServer(self.gateway)

    def test_block_preinit_calls(self):
        r = self.s.handle({'jsonrpc':'2.0','id':1,'method':'tools/list'})
        self.assertIn('error', r)

    def test_handshake(self):
        r = self.s.handle({'jsonrpc':'2.0','id':1,'method':'initialize',
                           'params': {'protocolVersion':'2025-11-25','clientInfo':{'name':'test','version':'1'}}})
        self.assertEqual(r['result']['protocolVersion'], '2025-11-25')
        self.assertIn('tools', r['result']['capabilities'])
        self.assertIsNone(self.s.handle({'jsonrpc':'2.0','method':'notifications/initialized'}))

    def test_unknown_method(self):
        self.test_handshake()
        self.assertEqual(self.s.handle({'jsonrpc':'2.0','id':2,'method':'unknown'})['error']['code'], -32601)

    def test_mcp_tools_read_only(self):
        self.test_handshake()
        manifest = self.s.handle({'jsonrpc':'2.0','id':2,'method':'tools/list'})['result']['tools']
        names = {x['name'] for x in manifest}
        self.assertIn('rai_workspace_read', names)
        self.assertNotIn('rai_shell_execute', names)
        self.assertFalse(any('write' in n or 'exec' in n for n in names))

    def test_mcp_tool_call(self):
        self.test_handshake()
        response = self.s.handle({'jsonrpc':'2.0','id':3,'method':'tools/call',
                                  'params': {'name':'rai_health','arguments':{}}})
        self.assertEqual(json.loads(response['result']['content'][0]['text'])['mode'],'read-only')

    def test_stdio_json_lines(self):
        data = '\n'.join([
            json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}}),
            json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'}),
            json.dumps({'jsonrpc':'2.0','id':2,'method':'tools/list'})]) + '\n'
        out = io.StringIO()
        self.s.serve(io.StringIO(data), out)
        responses = [json.loads(x) for x in out.getvalue().splitlines()]
        self.assertEqual(len(responses),2)
        self.assertEqual(responses[1]['id'],2)

    def test_workspace_read(self):
        (self.root/'hello.txt').write_text('Привет GPT', encoding='utf-8')
        self.assertEqual(self.gateway.read_file('hello.txt')['text'],'Привет GPT')

    def test_workspace_lists_files_without_protected(self):
        (self.root/'hello.txt').write_text('hello')
        (self.root/'.env').write_text('secret')
        self.assertEqual([x['name'] for x in self.gateway.list_files()['entries']], ['hello.txt'])

    def test_reject_parent_traversal(self):
        with self.assertRaises(FabricError):
            self.gateway.read_file('../outside.txt')

    def test_reject_absolute_path(self):
        with self.assertRaises(FabricError):
            self.gateway.read_file(str(self.root/'hello.txt'))

    def test_reject_secrets(self):
        (self.root/'.env').write_text('password')
        with self.assertRaises(FabricError):
            self.gateway.read_file('.env')

    def test_reject_sqlite_file(self):
        with self.assertRaises(FabricError):
            self.gateway.read_file('state.db')

    def test_reject_symlink(self):
        (self.root/'foo.txt').write_text('file')
        try:
            (self.root/'bar.txt').symlink_to(self.root/'foo.txt')
        except (OSError, NotImplementedError):
            self.skipTest('ОС запрещает создание символических ссылок')
        with self.assertRaises(FabricError):
            self.gateway.read_file('bar.txt')

    def test_large_file_limit(self):
        (self.root/'huge.txt').write_bytes(b'x'*32769)
        with self.assertRaises(FabricError):
            self.gateway.read_file('huge.txt')

    def test_task_get_does_not_expose_lease_token(self):
        self.db.submit('test','mock',str(self.root),task_id='t1')
        token = self.db.claim('w')['lease_token']
        body = json.dumps(self.gateway.invoke('rai_task_get',{'task_id':'t1'}))
        self.assertNotIn(token, body)
        self.assertNotIn('lease_hash',body)

    def test_gpu_probe_returns_available_key(self):
        self.assertIn('available',self.gateway.gpu_status())

    def test_git_probe_returns_available_key(self):
        self.assertIn('available',self.gateway.git_status())

if __name__ == '__main__':
    unittest.main()
