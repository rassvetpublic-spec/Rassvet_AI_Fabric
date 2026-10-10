"""Офлайн-испытания Codex JSON-RPC: никакой OAuth, сети или запуска модели."""
import json
import unittest

from rai_fabric.codex_protocol import CodexAppProtocol, CodexProtocolError


class CodexProtocolTests(unittest.TestCase):
    def setUp(self):
        self.driver = CodexAppProtocol()

    def initialize(self):
        init = self.driver.initialize()
        self.assertEqual(init['method'], 'initialize')
        self.assertEqual(init['params']['clientInfo']['name'], 'rassvet_ai_fabric')
        self.assertEqual(self.driver.consume({'id': init['id'], 'result': {}})['action'],
                         'INITIALIZE_ACK_REQUIRED')
        self.assertEqual(self.driver.initialized()['method'], 'initialized')

    def thread(self):
        self.initialize()
        start = self.driver.thread_start(model='модель-для-мока', cwd=r'C:\TEST\repo')
        self.assertEqual(start['params']['sandbox'], 'read-only')
        self.assertEqual(start['params']['approvalPolicy'], 'on-request')
        result = self.driver.consume({'id': start['id'], 'result': {'thread': {'id': 'thread-1'}}})
        self.assertEqual(result['thread_id'], 'thread-1')

    def turn(self):
        self.thread()
        start = self.driver.turn_start('Проверить минимальный проект')
        self.assertEqual(start['params']['threadId'], 'thread-1')
        self.assertEqual(start['params']['input'][0]['type'], 'text')
        self.driver.consume({'id': start['id'], 'result': {'turn': {'id': 'turn-1'}}})

    def test_full_offline_sequence_requires_terminal_success(self):
        self.turn()
        self.driver.consume({'method': 'item/agentMessage/delta', 'params': {
            'threadId': 'thread-1', 'turnId': 'turn-1', 'delta': 'Проверка '}})
        self.driver.consume({'method': 'item/agentMessage/delta', 'params': {
            'threadId': 'thread-1', 'turnId': 'turn-1', 'delta': 'пройдена'}})
        self.assertIsNone(self.driver.result()['verdict'])
        final = self.driver.consume({'method': 'turn/completed', 'params': {
            'threadId': 'thread-1', 'turnId': 'turn-1', 'turn': {'status': 'completed'}}})
        self.assertEqual(final['verdict'], 'PASS')
        self.assertEqual(self.driver.result()['response'], 'Проверка пройдена')
        self.assertEqual(self.driver.result()['cursor'], 'REVIEW_EVIDENCE')

    def test_failed_or_interrupted_turn_blocks(self):
        for status in ('failed', 'interrupted', 'inProgress', None):
            driver = CodexAppProtocol()
            init = driver.initialize()
            driver.consume({'id': init['id'], 'result': {}})
            driver.initialized()
            x = driver.thread_start(model='mock', cwd='test')
            driver.consume({'id': x['id'], 'result': {'thread': {'id': 't'}}})
            x = driver.turn_start('mock')
            driver.consume({'id': x['id'], 'result': {'turn': {'id': 'z'}}})
            verdict = driver.consume({'method': 'turn/completed', 'params': {
                'threadId': 't', 'turnId': 'z', 'turn': {'status': status}}})
            self.assertEqual(verdict['verdict'], 'BLOCKED')
            self.assertEqual(driver.result()['cursor'], 'VERIFY_EXTERNAL_SIDE_EFFECTS')

    def test_server_requests_are_never_approved(self):
        self.turn()
        verdict = self.driver.consume({'method': 'item/commandExecution/requestApproval',
                                       'id': 72, 'params': {'threadId': 'thread-1'}})
        self.assertEqual(verdict['verdict'], 'BLOCKED')
        self.assertEqual(verdict['cursor'], 'MANUAL_SERVER_REQUEST')
        self.assertEqual(verdict['error_code'], 'SERVER_REQUEST_REQUIRES_APPROVAL')
        with self.assertRaises(CodexProtocolError):
            self.driver.consume({'id': 72, 'result': {'approved': True}})

    def test_wrong_thread_identity_blocks_without_mixing_output(self):
        self.turn()
        with self.assertRaises(CodexProtocolError):
            self.driver.consume({'method': 'item/agentMessage/delta', 'params': {
                'threadId': 'other', 'turnId': 'turn-1', 'delta': 'secret'}})
        self.assertEqual(self.driver.result()['verdict'], 'BLOCKED')
        self.assertIsNone(self.driver.result()['response'])

    def test_unexpected_reply_blocks(self):
        initial = self.driver.initialize()
        res = self.driver.consume({'id': initial['id'] + 1, 'result': {}})
        self.assertEqual(res['cursor'], 'VERIFY_RPC_RESPONSE')

    def test_initialize_must_complete_before_thread(self):
        self.driver.initialize()
        with self.assertRaises(CodexProtocolError):
            self.driver.thread_start(model='mock', cwd='test')
        with self.assertRaises(CodexProtocolError):
            self.driver.initialized()

    def test_errors_are_sanitized_to_code(self):
        initial = self.driver.initialize()
        error = self.driver.consume({'id': initial['id'], 'error': {
            'code': 429, 'message': 'Authorization: Bearer very-secret'}})
        self.assertEqual(error['verdict'], 'BLOCKED')
        self.assertEqual(error['error_code'], '429')
        self.assertNotIn('very-secret', json.dumps(self.driver.result()))

    def test_missing_thread_or_turn_id_blocks(self):
        self.initialize()
        start = self.driver.thread_start(model='mock', cwd='test')
        response = self.driver.consume({'id': start['id'], 'result': {'thread': {}}})
        self.assertEqual(response['cursor'], 'VERIFY_THREAD_ID')

    def test_output_limit_fails_closed(self):
        self.turn()
        response = self.driver.consume({'method': 'item/agentMessage/delta', 'params': {
            'threadId': 'thread-1', 'turnId': 'turn-1', 'delta': 'а' * 65537}})
        self.assertEqual(response['error_code'], 'OUTPUT_TOO_LARGE')

    def test_decode_invalid_or_large_lines(self):
        with self.assertRaises(CodexProtocolError):
            CodexAppProtocol.decode_line(b'!invalid')
        with self.assertRaises(CodexProtocolError):
            CodexAppProtocol.decode_line(b'a' * 262145)
        with self.assertRaises(CodexProtocolError):
            CodexAppProtocol.decode_line(b'[]')
        valid = CodexAppProtocol.decode_line(b'{"id":1,"result":{}}\n')
        self.assertEqual(valid['id'], 1)

    def test_notifications_cannot_claim_completion(self):
        self.turn()
        self.driver.consume({'method': 'item/completed', 'params': {
            'threadId': 'thread-1', 'turnId': 'turn-1'}})
        self.assertIsNone(self.driver.result()['verdict'])

    def test_duplicate_terminal_event_rejected(self):
        self.turn()
        self.driver.consume({'method': 'turn/completed', 'params': {
            'threadId': 'thread-1', 'turnId': 'turn-1', 'turn': {'status': 'completed'}}})
        with self.assertRaises(CodexProtocolError):
            self.driver.consume({'method': 'turn/completed', 'params': {
                'threadId': 'thread-1', 'turnId': 'turn-1', 'turn': {'status': 'completed'}}})


if __name__ == '__main__':
    unittest.main()
