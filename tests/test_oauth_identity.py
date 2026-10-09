"""Офлайн-тесты подписи JWT с одноразовыми тестовыми RSA-ключами."""
import time
import unittest

try:
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
except ImportError:
    jwt = None
    rsa = None

from rai_fabric.oauth_identity import (
    ISSUER, IdentityVerificationError, VerifiedIdentity, confirmed_plan_scope, verify_id_token,
)


@unittest.skipUnless(jwt is not None and rsa is not None, "Нужен набор пакетов [security]")
class TokenIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub = jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key(), as_dict=True)
        pub.update({'kid': 'test-rsa-1', 'use': 'sig', 'alg': 'RS256'})
        cls.jwks = {'keys': [pub]}
        cls.nonce = 'test-nonce-which-is-long-enough'
        cls.client = 'oaiapp_offline_test'

    def jwt(self, claims=None, *, key=None, headers=None, algorithm='RS256'):
        now = int(time.time())
        payload = dict(iss=ISSUER, aud=self.client, sub='offline-subject-1',
                       nonce=self.nonce, iat=now-1, exp=now+300)
        if claims:
            payload.update(claims)
        return jwt.encode(payload, key or self.key, algorithm=algorithm,
                          headers={'kid':'test-rsa-1',**(headers or {})})

    def verify(self, token, **kwargs):
        return verify_id_token(token, jwks=kwargs.pop('jwks',self.jwks),
                               issued_client_id=kwargs.pop('issued_client_id',self.client),
                               expected_nonce=kwargs.pop('expected_nonce',self.nonce), **kwargs)

    def test_valid_signature_and_verified_identity(self):
        result = self.verify(self.jwt())
        self.assertIsInstance(result,VerifiedIdentity)
        self.assertEqual(result.subject,'offline-subject-1')
        self.assertFalse(result.public_report()['plan_permission_verified'])

    def test_only_validated_identity_may_confirm_scope(self):
        result = self.verify(self.jwt())
        self.assertFalse(confirmed_plan_scope(None,'chatgpt.tokens.use.direct'))
        self.assertFalse(confirmed_plan_scope(result,'openid email'))
        self.assertTrue(confirmed_plan_scope(result,'openid chatgpt.tokens.use.direct'))
        self.assertFalse(confirmed_plan_scope(result,'prefix.chatgpt.tokens.use.direct'))

    def test_bad_signature_rejected(self):
        with self.assertRaises(IdentityVerificationError):
            self.verify(self.jwt(key=self.other_key))

    def test_wrong_issuer_audience_nonce_subject_expiration(self):
        cases = [
            {'iss':'https://evil.example'},
            {'aud':'oaiapp_wrong'},
            {'nonce':'wrong-nonce-value'},
            {'sub':''},
            {'exp':int(time.time())-100},
            {'iat':int(time.time())+1000},
            {'nbf':int(time.time())+1000},
            {'exp':int(time.time())-60,'iat':int(time.time())-120},
        ]
        for claims in cases:
            with self.subTest(claims=claims),self.assertRaises(IdentityVerificationError):
                self.verify(self.jwt(claims))

    def test_no_kid_and_unknown_kid(self):
        for kid in ('unknown',''):
            with self.subTest(kid=kid), self.assertRaises(IdentityVerificationError):
                self.verify(self.jwt(headers={'kid':kid}))

    def test_duplicate_jwks_kid_is_rejected(self):
        keys=self.jwks['keys']
        with self.assertRaises(IdentityVerificationError):
            self.verify(self.jwt(),jwks={'keys':[keys[0],keys[0]]})

    def test_no_unsigned_or_wrong_algorithm(self):
        with self.assertRaises(IdentityVerificationError):
            self.verify(jwt.encode({'iss':ISSUER},key='',algorithm='none',headers={'kid':'test-rsa-1'}))
        with self.assertRaises(IdentityVerificationError):
            self.verify(self.jwt(headers={'jku':'https://evil.example/jwks.json'}))

    def test_jwk_in_header_is_not_trusted(self):
        with self.assertRaises(IdentityVerificationError):
            self.verify(self.jwt(headers={'jwk':self.jwks['keys'][0]}))

    def test_wrong_jwks_key_type_and_private_key_rejected(self):
        pub=dict(self.jwks['keys'][0]);pub['use']='enc'
        with self.assertRaises(IdentityVerificationError):
            self.verify(self.jwt(),jwks={'keys':[pub]})
        pub=dict(self.jwks['keys'][0]);pub['d']='private'
        with self.assertRaises(IdentityVerificationError):
            self.verify(self.jwt(),jwks={'keys':[pub]})

    def test_multi_audience_requires_authorized_party(self):
        with self.assertRaises(IdentityVerificationError):
            self.verify(self.jwt({'aud':[self.client,'unrelated']}))
        result=self.verify(self.jwt({'aud':[self.client,'unrelated'],'azp':self.client}))
        self.assertEqual(result.client_id,self.client)
        with self.assertRaises(IdentityVerificationError):
            self.verify(self.jwt({'aud':[self.client,'unrelated'],'azp':'oaiapp_other'}))

    def test_reject_dynamic_client_and_bad_nonce_argument(self):
        with self.assertRaises(IdentityVerificationError):
            self.verify(self.jwt(),issued_client_id='dynamic_agent_client')
        with self.assertRaises(IdentityVerificationError):
            self.verify(self.jwt(),expected_nonce='short')

    def test_invalid_oversize_payload_and_jwks(self):
        with self.assertRaises(IdentityVerificationError):
            self.verify('not.a.jwt')
        with self.assertRaises(IdentityVerificationError):
            self.verify('z'*32769)
        with self.assertRaises(IdentityVerificationError):
            self.verify(self.jwt(),jwks={'keys':[]})

    def test_audit_messages_never_include_token_or_subject(self):
        raw=self.jwt({'sub':'secret-identity'})
        identity=self.verify(raw)
        s=repr(identity.public_report())
        self.assertNotIn(raw,s)
        self.assertNotIn('secret-identity',s)
        self.assertNotIn('secret-identity',repr(identity))
        try: self.verify(raw,expected_nonce='wrong-nonce-long-enough')
        except IdentityVerificationError as exc:
            self.assertNotIn(raw,str(exc))
            self.assertNotIn('secret-identity',str(exc))


if __name__=='__main__': unittest.main()
