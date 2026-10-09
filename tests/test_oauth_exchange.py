"""Проверяем подготовку обмена и ротации ТОЛЬКО на синтетических токенах."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import patch

import jwt
from jwt.algorithms import RSAAlgorithm
from cryptography.hazmat.primitives.asymmetric import rsa

from rai_fabric.oauth_readiness import (
    OAuthCallbackGuard, OAuthReadinessError, new_authorization_attempt,
)
from rai_fabric.oauth_exchange import (
    TokenExchangeError, SecretTokenRequest, code_request, refresh_request,
    exchange_code_offline, refresh_offline, _parse_response,
)
from rai_fabric.credential_store import _AtomicVaultStore
from rai_fabric.trusted_jwks import TrustedOpenAIKeys, DISCOVERY_URL, JWKS_URL
from rai_fabric.windows_vault import VaultError
from test_credential_store import FakeCipher, FakeGuard

HOST = 'urn:uuid:00000000-1111-4444-8888-000000000000'
SCOPE = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'


class OfflineOAuthExchangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwk = json.loads(RSAAlgorithm.to_jwk(cls.signing.public_key()))
        cls.jwk.update(kid='synthetic-key', use='sig', alg='RS256')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = _AtomicVaultStore(Path(self.tmp.name) / 'Rassvet_AI_Fabric' / 'oauth_v1',
                                       FakeCipher(), FakeGuard())
        self.now = int(time.time())
        self.attempt = new_authorization_attempt(host_id=HOST, callback_port=18775)
        self.guard = OAuthCallbackGuard(self.attempt)
        self.issued_client = 'oaiapp_fake-client'
        self.url = self._callback()
        self.keys = TrustedOpenAIKeys(download=self._trusted_data)
        self.transport_calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def _callback(self, **updates):
        values = dict(state=self.attempt.state, code='FAKE_AUTHORIZATION_CODE_NOT_REAL_12345',
                      client_id=self.issued_client)
        values.update(updates)
        return self.attempt.redirect_uri + '?' + urlencode(values)

    def _id_token(self, *, nonce=None, subject='subject_fake', issued_client=None):
        return jwt.encode(dict(iss='https://auth.openai.com',
                               aud=issued_client or self.issued_client, sub=subject,
                               nonce=nonce if nonce is not None else self.attempt.nonce,
                               iat=self.now-10, exp=self.now+3600),
                          self.signing, algorithm='RS256', headers={'kid':'synthetic-key'})

    def _trusted_data(self, url, limit):
        if url == DISCOVERY_URL:
            return json.dumps(dict(issuer='https://auth.openai.com', jwks_uri=JWKS_URL)).encode()
        if url == JWKS_URL:
            return json.dumps(dict(keys=[self.jwk])).encode()
        raise AssertionError('Нельзя перенаправлять TLS на другой ресурс')

    def _response(self, *, refresh='FAKE_REFRESH_ROTATED_AABBCCDDEEFF',
                  access='FAKE_ACCESS_ROTATED_AABBCCDDEEFF', token=None, scope=SCOPE,
                  expires=3600, included_id=True):
        record = dict(access_token=access, refresh_token=refresh, token_type='Bearer',
                      expires_in=expires, scope=scope)
        if included_id:
            record['id_token'] = token or self._id_token()
        return 200, json.dumps(record).encode()

    def _transport(self, response):
        def call(request):
            self.transport_calls.append(request)
            return response
        return call

    def _authorize(self, *, response=None, returning_identity=None, expected_revision=None):
        return exchange_code_offline(guard=self.guard, callback_url=self.url,
                                     transport=self._transport(response or self._response()),
                                     keys=self.keys, vault=self.store, now=self.now,
                                     returning_identity=returning_identity,
                                     expected_revision=expected_revision)

    def test_prepared_code_request_contains_only_expected_fields(self):
        private = self.guard.consume_private(self.url)
        request = code_request(private)
        self.assertEqual(request.endpoint,'https://auth.openai.com/api/accounts/oauth/token')
        self.assertEqual(request.method,'POST')
        self.assertEqual([k for k,v in request.form],
                         ['grant_type','client_id','code','code_verifier','redirect_uri','resource'])
        self.assertEqual(dict(request.form)['client_id'], self.issued_client)
        self.assertEqual(dict(request.form)['redirect_uri'],self.attempt.redirect_uri)
        self.assertNotIn('FAKE_AUTHORIZATION_CODE_NOT_REAL',repr(request))
        self.assertNotIn(self.attempt.code_verifier,repr(request))
        self.assertNotIn(self.attempt.nonce,repr(private))
        self.assertFalse(request.public_report()['request_sent'])

    def test_callback_cannot_be_reused_between_public_and_private_paths(self):
        self.guard.consume_private(self.url)
        with self.assertRaises(OAuthReadinessError):
            self.guard.consume(self.url)
        with self.assertRaises(OAuthReadinessError):
            self.guard.consume_private(self.url)
        g=OAuthCallbackGuard(self.attempt)
        g.consume(self.url)
        with self.assertRaises(OAuthReadinessError):
            g.consume_private(self.url)

    def test_invalid_callback_blocks_transport(self):
        self.url=self._callback(state='wrong')
        with self.assertRaises(OAuthReadinessError):
            self._authorize()
        self.assertEqual(self.transport_calls,[])

    def test_successful_exchange_verifies_real_signature_and_stores(self):
        result=self._authorize()
        self.assertEqual(result.operation,'authorization_code')
        self.assertTrue(result.plan_scope_granted)
        self.assertTrue(result.public_report()['identity_revalidated_in_operation'])
        self.assertFalse(result.public_report()['model_request_performed'])
        self.assertEqual(len(self.transport_calls),1)
        self.assertEqual(self.store.load(result.identity).revision,result.revision)
        self.assertNotIn('subject_fake',repr(result))
        self.assertNotIn('FAKE_ACCESS',repr(result))

    def test_rejects_wrong_nonce_without_creating_record(self):
        bad=self._response(token=self._id_token(nonce='wrong_nonce_12345678'))
        with self.assertRaises(Exception):
            self._authorize(response=bad)
        self.assertFalse(any(Path(self.tmp.name).rglob('*.dpapi')))

    def test_rejects_wrong_audience_and_invalid_signature(self):
        for token in (self._id_token(issued_client='oaiapp_other'),
                      self._id_token()[:-2]+'xx'):
            with self.subTest(token=token[:8]):
                self.guard=OAuthCallbackGuard(self.attempt)
                with self.assertRaises(Exception):
                    self._authorize(response=self._response(token=token))
        self.assertFalse(any(Path(self.tmp.name).rglob('*.dpapi')))

    def test_missing_plan_scope_is_not_permission_to_call_model(self):
        result=self._authorize(response=self._response(scope='openid offline_access'))
        self.assertFalse(result.plan_scope_granted)
        self.assertEqual(self.store.load(result.identity).credentials['scopes'],
                         ['openid','offline_access'])

    def test_missing_offline_access_is_not_persisted(self):
        with self.assertRaises(TokenExchangeError):
            self._authorize(response=self._response(scope='openid chatgpt.tokens.use.direct'))
        self.assertFalse(any(Path(self.tmp.name).rglob('*.dpapi')))

    def test_duplicate_json_fields_rejected_and_secret_redacted(self):
        body=b'{"scope":"openid offline_access", "scope":"openid offline_access"}'
        with self.assertRaises(TokenExchangeError) as ctx:
            _parse_response((200,body),operation='authorization_code')
        self.assertNotIn('FAKE',str(ctx.exception))

    def test_malformed_token_payloads_fail_closed(self):
        cases=[(200,b'not json'), (200,b'[]'),(200,b'{}'),
               (200,b'{' + b'A'*524289 + b'}'), (500,b'FAKE_PRIVATE_TOKEN'),
               (200,b'{"token_type":"Bearer","expires_in":NaN}')]
        for response in cases:
            with self.subTest(size=len(response[1])), self.assertRaises(TokenExchangeError):
                _parse_response(response, operation='authorization_code')

    def test_transport_exception_does_not_leak_secrets(self):
        def exploding(_):
            raise RuntimeError('FAKE_ACCESS_SECRET_SHOULD_NEVER_LEAK')
        with self.assertRaises(TokenExchangeError) as ctx:
            exchange_code_offline(guard=self.guard,callback_url=self.url,
                                  transport=exploding,keys=self.keys,vault=self.store)
        self.assertNotIn('FAKE_ACCESS_SECRET',str(ctx.exception))

    def test_returning_account_must_match_saved_identity(self):
        first=self._authorize()
        self.guard=OAuthCallbackGuard(self.attempt)
        with self.assertRaises(TokenExchangeError):
            self._authorize(response=self._response(token=self._id_token(subject='OTHER_SUBJECT')),
                            returning_identity=first.identity,expected_revision=first.revision)
        self.assertEqual(self.store.load(first.identity).revision,first.revision)

    def test_returning_account_can_rotate_under_revision_guard(self):
        first=self._authorize()
        self.guard=OAuthCallbackGuard(self.attempt)
        replacement=self._authorize(response=self._response(refresh='FAKE_SIGNIN_REFRESH_NEXT_12345678'),
                                     returning_identity=first.identity,expected_revision=first.revision)
        self.assertNotEqual(first.revision,replacement.revision)
        self.assertEqual(self.store.load(first.identity).revision,replacement.revision)

    def test_refresh_form_contains_issued_client_and_no_scope(self):
        cred=self.store.load(self._authorize().identity).credentials
        data=dict(refresh_request(cred).form)
        self.assertEqual(set(data),{'grant_type','client_id','refresh_token','resource'})
        self.assertEqual(data['grant_type'],'refresh_token')
        self.assertEqual(data['client_id'],self.issued_client)
        self.assertNotIn('scope',data)
        self.assertNotIn(cred['refresh_token'],repr(refresh_request(cred)))

    def test_refresh_atomically_rotates_both_tokens(self):
        first=self._authorize()
        before=self.store.load(first.identity)
        next_token='FAKE_REFRESH_02_ROTATED_123456789'
        self.transport_calls=[]
        result=refresh_offline(identity=first.identity,vault=self.store,
                               transport=self._transport(self._response(
                                   refresh=next_token,access='FAKE_ACCESS_02_ROTATED_123456789',
                                   included_id=False)), now=self.now+3400)
        saved=self.store.load(first.identity)
        self.assertEqual(saved.credentials['refresh_token'],next_token)
        self.assertNotEqual(before.credentials['access_token'],saved.credentials['access_token'])
        self.assertEqual(saved.credentials['id_token'],before.credentials['id_token'])
        self.assertNotEqual(result.revision, first.revision)
        self.assertEqual(len(self.transport_calls),1)
        self.assertFalse(any(self.store._root.glob('*.refresh.lock')))

    def test_refresh_too_early_does_not_call_transport_or_block_future(self):
        first=self._authorize()
        self.transport_calls=[]
        with self.assertRaisesRegex(TokenExchangeError,'ещё не наступил'):
            refresh_offline(identity=first.identity,vault=self.store,
                            transport=self._transport(self._response()),now=self.now+1)
        self.assertFalse(self.transport_calls)
        self.assertFalse(any(self.store._root.glob('*.refresh.lock')))

    def test_second_refresh_blocked_while_first_is_in_flight(self):
        first=self._authorize()
        with self.store.refresh_lock(first.identity):
            with self.assertRaisesRegex(TokenExchangeError,'сверки'):
                refresh_offline(identity=first.identity,vault=self.store,
                                transport=self._transport(self._response()),now=self.now+3500)
        self.assertFalse(self.transport_calls[1:])

    def test_network_failure_leaves_durable_blocking_lock(self):
        first=self._authorize()
        def broken(_):
            raise RuntimeError('FAKE_SECRET_IN_NETWORK_ERROR')
        with self.assertRaises(TokenExchangeError) as ctx:
            refresh_offline(identity=first.identity,vault=self.store,
                            transport=broken,now=self.now+3500)
        self.assertNotIn('FAKE_SECRET',str(ctx.exception))
        self.assertTrue(any(self.store._root.glob('*.refresh.lock')))
        with self.assertRaises(TokenExchangeError):
            refresh_offline(identity=first.identity,vault=self.store,
                            transport=self._transport(self._response()),now=self.now+3500)

    def test_server_returning_unchanged_refresh_is_blocked(self):
        first=self._authorize()
        old=self.store.load(first.identity).credentials['refresh_token']
        with self.assertRaisesRegex(TokenExchangeError,'не заменил'):
            refresh_offline(identity=first.identity,vault=self.store,
                            transport=self._transport(self._response(refresh=old)),now=self.now+3500)
        self.assertTrue(any(self.store._root.glob('*.refresh.lock')))

    def test_refresh_scope_drop_disables_plan_permission(self):
        first=self._authorize()
        updated=refresh_offline(identity=first.identity,vault=self.store,
                                transport=self._transport(self._response(
                                    scope='openid offline_access',
                                    refresh='FAKE_SCOPE_DROP_REFRESH_NEXT_123456789',
                                    included_id=False)),now=self.now+3500)
        self.assertFalse(updated.plan_scope_granted)
        self.assertNotIn('chatgpt.tokens.use.direct',self.store.load(first.identity).credentials['scopes'])

    def test_local_write_fails_after_successful_refresh_and_blocks_retry(self):
        first=self._authorize()
        original_revision=self.store.load(first.identity).revision
        with patch.object(self.store, 'save', side_effect=VaultError('FAKE_PRIVATE_SAVE_ERROR')):
            with self.assertRaises(TokenExchangeError) as ctx:
                refresh_offline(identity=first.identity, vault=self.store,
                                transport=self._transport(self._response(
                                    refresh='FAKE_REMOTE_ALREADY_ROTATED_123456789',
                                    included_id=False)), now=self.now+3500)
        self.assertNotIn('FAKE_PRIVATE', str(ctx.exception))
        self.assertEqual(self.store.load(first.identity).revision, original_revision)
        self.assertTrue(any(self.store._root.glob('*.refresh.lock')))

    def test_credentials_remain_redacted_on_write_error(self):
        first=self._authorize()
        self.guard=OAuthCallbackGuard(self.attempt)
        with self.assertRaises(TokenExchangeError) as ctx:
            self._authorize(returning_identity=first.identity,expected_revision='a'*32)
        self.assertNotIn('FAKE_ACCESS',str(ctx.exception))
        self.assertEqual(self.store.load(first.identity).revision,first.revision)

    def test_no_model_network_or_browser_runtime_in_module(self):
        import inspect
        from rai_fabric import oauth_exchange
        source=inspect.getsource(oauth_exchange)
        for forbidden in ['urllib.request', 'requests.post', 'webbrowser.open',
                          'subprocess.Popen', 'ACCESS_TOKEN =']:
            self.assertNotIn(forbidden,source)


if __name__ == '__main__':
    unittest.main()
