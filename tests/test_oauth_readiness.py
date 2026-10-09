"""Офлайн-тесты OAuth: ни один тест не создаёт сетевые запросы и не читает токены."""
import hashlib
import base64
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit

from rai_fabric.oauth_readiness import (
    AUTHORIZATION_URL, RESOURCE, REQUESTED_SCOPES, OAuthReadinessError, OAuthCallbackGuard,
    new_authorization_attempt, plan_scope_granted, validate_authorization_callback,
)


class OAuthReadinessTests(unittest.TestCase):
    def setUp(self):
        self.attempt = new_authorization_attempt(host_id="rassvet_test_host", callback_port=18775)

    def callback(self, **updates):
        params = {"state": self.attempt.state, "code": "TEST_CODE_NOT_REAL", "client_id": "oaiapp_test"}
        params.update(updates)
        return self.attempt.redirect_uri + "?" + urlencode(params)

    def test_dynamic_registration_uses_exact_host_and_scopes(self):
        url = urlsplit(self.attempt.authorization_url)
        q = parse_qs(url.query)
        self.assertEqual(f"{url.scheme}://{url.netloc}{url.path}", AUTHORIZATION_URL)
        self.assertEqual(q['redirect_uri'], ["http://127.0.0.1:18775/auth/callback"])
        self.assertEqual(q['resource'], [RESOURCE])
        self.assertEqual(q['scope'], [REQUESTED_SCOPES])
        self.assertEqual(q['client_id'], ['dynamic_agent_client'])
        self.assertEqual(q['agent_name_hint'], ['rassvet_ai_fabric'])
        self.assertEqual(q['code_challenge_method'], ['S256'])
        expected = base64.urlsafe_b64encode(hashlib.sha256(self.attempt.code_verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')
        self.assertEqual(q['code_challenge'], [expected])
        self.assertNotIn('code_verifier', q)

    def test_unique_secrets_each_attempt(self):
        other = new_authorization_attempt(host_id="rassvet_test_host", callback_port=18775)
        self.assertNotEqual(self.attempt.state, other.state)
        self.assertNotEqual(self.attempt.nonce, other.nonce)
        self.assertNotEqual(self.attempt.code_verifier, other.code_verifier)

    def test_redacted_metadata_no_sensitive_values(self):
        result = str(self.attempt.public_report()) + repr(self.attempt)
        for sensitive in [self.attempt.state, self.attempt.nonce, self.attempt.code_verifier]:
            self.assertNotIn(sensitive, result)
        self.assertFalse(self.attempt.public_report()['subscription_permission_verified'])

    def test_valid_callback_is_not_entitlement(self):
        report = validate_authorization_callback(self.attempt, self.callback())
        self.assertTrue(report['state_verified'])
        self.assertFalse(report['subscription_permission_verified'])
        self.assertFalse(report['id_token_signature_verified'])
        self.assertNotIn('TEST_CODE_NOT_REAL', str(report))

    def test_replay_and_wrong_state_block(self):
        guard = OAuthCallbackGuard(self.attempt)
        guard.consume(self.callback())
        with self.assertRaisesRegex(OAuthReadinessError, "Повторное"):
            guard.consume(self.callback())
        with self.assertRaisesRegex(OAuthReadinessError, "state"):
            validate_authorization_callback(self.attempt, self.callback(state="wrong"))

    def test_long_callback_is_rejected(self):
        with self.assertRaises(OAuthReadinessError):
            validate_authorization_callback(self.attempt, self.callback() + "&n=" + "a" * 16500)

    def test_duplicate_state_rejected(self):
        with self.assertRaisesRegex(OAuthReadinessError, "Повторяющиеся"):
            validate_authorization_callback(self.attempt, self.callback() + "&state=duplicate")

    def test_access_denied_never_succeeds(self):
        with self.assertRaisesRegex(OAuthReadinessError, "отклонена"):
            validate_authorization_callback(self.attempt, self.callback(error="access_denied"))

    def test_callback_wrong_host_port_path_scheme_blocked(self):
        for url in [self.callback().replace('127.0.0.1','localhost'),
                    self.callback().replace(':18775', ':18776'),
                    self.callback().replace('/auth/callback','/callback'),
                    self.callback().replace('http://','https://'),
                    self.callback()+'#fragment']:
            with self.subTest(url=url), self.assertRaises(OAuthReadinessError):
                validate_authorization_callback(self.attempt, url)

    def test_register_requires_issued_client_id(self):
        for returned in ('', 'dynamic_agent_client'):
            with self.assertRaises(OAuthReadinessError):
                validate_authorization_callback(self.attempt, self.callback(client_id=returned))

    def test_returning_client_id_cannot_change(self):
        attempt = new_authorization_attempt(host_id='host_test', callback_port=18775, client_id='oaiapp_saved')
        self.assertNotIn('agent_name_hint', parse_qs(urlsplit(attempt.authorization_url).query))
        for returned in ['oaiapp_other']:
            url = attempt.redirect_uri + '?' + urlencode({'state':attempt.state, 'code':'example', 'client_id': returned})
            with self.assertRaisesRegex(OAuthReadinessError, 'подменить'):
                validate_authorization_callback(attempt, url)
        url = attempt.redirect_uri + '?' + urlencode({'state':attempt.state,'code':'example'})
        self.assertTrue(validate_authorization_callback(attempt,url)['state_verified'])

    def test_invalid_host_and_port(self):
        for host in ('', 'bad host', 'a'*129):
            with self.assertRaises(OAuthReadinessError):
                new_authorization_attempt(host_id=host,callback_port=18775)
        for port in (None, True, 80, 65536, '18775'):
            with self.assertRaises(OAuthReadinessError):
                new_authorization_attempt(host_id='safe_host',callback_port=port)

    def test_scope_check_does_not_assume_permission(self):
        self.assertFalse(plan_scope_granted('openid profile email'))
        self.assertFalse(plan_scope_granted(None))
        self.assertFalse(plan_scope_granted('other.chatgpt.tokens.use.direct'))
        self.assertTrue(plan_scope_granted('openid profile chatgpt.tokens.use.direct'))


if __name__ == '__main__':
    unittest.main()
