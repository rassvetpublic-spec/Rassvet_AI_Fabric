"""Проверка доверенного OIDC: только синтетические ключи, ноль HTTP-вызовов."""
import json
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from rai_fabric.trusted_jwks import (
    DISCOVERY_URL, JWKS_URL, TrustedKeyError, TrustedOpenAIKeys,
    _decode_strict_json, _https_get_once, _validate_discovery,
    _validate_jwks,
)

ISSUER = 'https://auth.openai.com'


def synthetic_key():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(RSAAlgorithm.to_jwk(private.public_key()))
    public.update({'kid': 'kid1', 'use': 'sig', 'alg': 'RS256'})
    return private, public


class SyntheticIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private, cls.public = synthetic_key()

    def setUp(self):
        self.events = []
        self.time = 1000.0
        self.issued = 'oaiapp_synthetic'
        self.nonce = 'synthetic-nonce-12345678'
        self.discovery = json.dumps({'issuer': ISSUER, 'jwks_uri': JWKS_URL}).encode()
        self.jwks = json.dumps({'keys': [self.public]}).encode()

        def get(url, limit):
            self.events.append(url)
            if url == DISCOVERY_URL:
                return self.discovery
            if url == JWKS_URL:
                return self.jwks
            raise AssertionError('Переход к недоверенному адресу')
        self.provider = TrustedOpenAIKeys(download=get, clock=lambda: self.time)

    def signed(self, *, kid='kid1'):
        return jwt.encode({'iss': ISSUER, 'aud': self.issued, 'sub': 'synthetic-sub',
                           'nonce': self.nonce, 'iat': 100, 'exp': 4102444800},
                          self.private, algorithm='RS256', headers={'kid': kid})

    def test_no_network_before_explicit_request(self):
        self.assertEqual(self.events, [])
        self.assertFalse(self.provider.status().has_fresh_keys)

    def test_one_time_fetch_caches_keys(self):
        self.provider.get_jwks()
        self.assertEqual(self.events, [DISCOVERY_URL, JWKS_URL])
        self.provider.get_jwks()
        self.assertEqual(len(self.events), 2)
        self.assertTrue(self.provider.status().has_fresh_keys)

    def test_live_signature_verifies_only_synthetic_token(self):
        subject = self.provider.verify(self.signed(), issued_client_id=self.issued,
                                       expected_nonce=self.nonce)
        self.assertEqual(subject.subject, 'synthetic-sub')
        self.assertNotIn('synthetic-sub', repr(subject))

    def test_ttl_expires_and_refetches(self):
        self.provider.get_jwks()
        self.time += 601
        self.provider.get_jwks()
        self.assertEqual(len(self.events), 4)

    def test_failed_refresh_never_uses_stale_cache(self):
        self.provider.get_jwks()
        self.time += 610
        self.discovery = b'{"issuer":"https://evil", "jwks_uri":"https://evil/jwks"}'
        with self.assertRaises(TrustedKeyError):
            self.provider.get_jwks()
        self.assertFalse(self.provider.status().has_fresh_keys)

    def test_unknown_kid_is_rate_limited_and_not_trusted(self):
        self.provider.get_jwks()
        with self.assertRaises(TrustedKeyError):
            self.provider.verify(self.signed(kid='missing'), issued_client_id=self.issued,
                                 expected_nonce=self.nonce)
        self.assertEqual(len(self.events), 2)
        self.time += 31
        with self.assertRaises(TrustedKeyError):
            self.provider.verify(self.signed(kid='missing'), issued_client_id=self.issued,
                                 expected_nonce=self.nonce)
        self.assertEqual(len(self.events), 4)

    def test_rotation_new_kid_after_ttl(self):
        self.provider.get_jwks()
        self.time += 31
        new_pub = dict(self.public, kid='kid2')
        self.jwks = json.dumps({'keys':[new_pub]}).encode()
        self.provider.get_jwks(key_id='kid2')
        self.assertEqual(len(self.events), 4)

    def test_discovery_blocks_host_switch_and_scheme(self):
        for bad in ['http://auth.openai.com/.well-known/jwks.json',
                    'https://example.com/jwks',
                    'https://auth.openai.com.evil/jwks']:
            with self.subTest(bad=bad), self.assertRaises(TrustedKeyError):
                _validate_discovery(json.dumps({'issuer':ISSUER, 'jwks_uri':bad}).encode())

    def test_duplicate_json_fields_blocked(self):
        with self.assertRaises(TrustedKeyError):
            _decode_strict_json(b'{"keys":[],"keys":[]}', 1024)

    def test_duplicate_and_private_keys_blocked(self):
        for keys in [[self.public, self.public], [dict(self.public, d='secret')],
                     [dict(self.public, kty='EC')], [dict(self.public, kid='bad/')]]:
            with self.subTest(keys=keys), self.assertRaises(TrustedKeyError):
                _validate_jwks(json.dumps({'keys':keys}).encode())

    def test_body_size_and_non_json_are_blocked(self):
        for data in [b'', b'A'*150000, b'not-json', b'[]', b'{"keys":NaN}']:
            with self.subTest(size=len(data)), self.assertRaises(TrustedKeyError):
                _validate_jwks(data)

    def test_custom_url_is_forbidden_before_network(self):
        with self.assertRaises(TrustedKeyError):
            _https_get_once('https://example.com', 1024)

    def test_invalid_timing_fails_closed(self):
        with self.assertRaises(TrustedKeyError):
            TrustedOpenAIKeys(ttl_seconds=1)

    def test_failed_network_never_logs_exception_text(self):
        def fails(*args):
            raise RuntimeError('token_private_DO_NOT_LOG')
        provider = TrustedOpenAIKeys(download=fails)
        with self.assertRaises(TrustedKeyError) as ctx:
            provider.get_jwks()
        self.assertNotIn('token_private_DO_NOT_LOG', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
