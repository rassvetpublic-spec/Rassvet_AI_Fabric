"""Зашифрованная запись, атомарная CAS-ротация и Windows ACL. Только фальшивые токены."""
import copy
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from rai_fabric.credential_store import (
    WindowsCredentialVault, _AtomicVaultStore, _parse_envelope,
    _validate_credential, _SCHEMA,
)
from rai_fabric.oauth_identity import VerifiedIdentity
from rai_fabric.windows_vault import VaultError, default_vault_root


class FakeCipher:
    """НЕ шифрование: используется исключительно внутри тестов ядра."""
    def protect(self, value):
        return b'TEST_ONLY_FAKE_DPAPI_' + value[::-1]

    def unprotect(self, value):
        if not value.startswith(b'TEST_ONLY_FAKE_DPAPI_'):
            raise VaultError('Шифротекст повреждён')
        return value[len(b'TEST_ONLY_FAKE_DPAPI_'):][::-1]


class FakeGuard:
    def __init__(self):
        self.restrict_count = 0

    def reject_reparse(self, path, *, required=False):
        p = Path(path)
        if p.is_symlink():
            raise VaultError('Обнаружена ссылка')
        if required and not p.exists():
            raise VaultError('Не найден объект')

    def restrict(self, path):
        self.reject_reparse(path, required=True)
        self.restrict_count += 1

    def verify(self, path):
        self.reject_reparse(path, required=True)


def identity():
    return VerifiedIdentity(issuer='https://auth.openai.com',
                            client_id='oaiapp_fake-client', subject='subject_fake',
                            issued_at=1, expires_at=4102444800)


def credentials(*, refresh='FAKE_REFRESH_TOKEN_NOT_REAL_123456789'):
    return dict(issuer='https://auth.openai.com', client_id='oaiapp_fake-client',
                subject='subject_fake', token_type='Bearer',
                access_token='FAKE_ACCESS_TOKEN_NOT_REAL_123456789',
                refresh_token=refresh, id_token='FAKE_ID_TOKEN_NOT_REAL_123456789',
                ext_agent_host_id='urn:uuid:00000000-1111-4444-8888-000000000000',
                scopes=['openid','offline_access'], saved_at=100, expires_at=3500)


class AtomicVaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)/'Rassvet_AI_Fabric'/'oauth_v1'
        self.guard = FakeGuard()
        self.store = _AtomicVaultStore(self.root, FakeCipher(), self.guard)
        self.id = identity()

    def tearDown(self):
        self.tmp.cleanup()

    def test_does_not_create_files_at_construct_time(self):
        self.assertFalse(self.root.exists())

    def test_create_load_and_hide_repr(self):
        rev = self.store.save(self.id, credentials())
        self.assertEqual(len(rev), 32)
        saved = self.store.load(self.id)
        self.assertEqual(saved.revision, rev)
        self.assertEqual(saved.credentials['access_token'], credentials()['access_token'])
        self.assertNotIn('FAKE_ACCESS', repr(saved))
        self.assertEqual(len(list(self.root.glob('*.dpapi'))), 1)
        self.assertEqual(self.guard.restrict_count, 3)  # корень, lock, temp
        blob = next(self.root.glob('*.dpapi')).read_bytes()
        self.assertNotIn(b'FAKE_ACCESS', blob)

    def test_refresh_rotation_replaces_tokens_in_one_file(self):
        rev1 = self.store.save(self.id, credentials())
        rev2 = self.store.save(self.id, credentials(refresh='FAKE_NEXT_REFRESH_TOKEN_123456789'),
                               expected_revision=rev1)
        self.assertNotEqual(rev1, rev2)
        self.assertEqual(self.store.load(self.id).credentials['refresh_token'],
                         'FAKE_NEXT_REFRESH_TOKEN_123456789')
        self.assertEqual(len(list(self.root.glob('*.dpapi'))), 1)
        self.assertEqual(list(self.root.glob('*.tmp')), [])
        self.assertEqual(list(self.root.glob('*.lock')), [])

    def test_overwrite_without_revision_refused(self):
        self.store.save(self.id, credentials())
        with self.assertRaises(VaultError):
            self.store.save(self.id, credentials())

    def test_missing_revision_refused(self):
        with self.assertRaises(VaultError):
            self.store.save(self.id, credentials(), expected_revision='a'*32)

    def test_stale_revision_refused_and_old_data_retained(self):
        first = self.store.save(self.id, credentials())
        self.store.save(self.id, credentials(refresh='FAKE_NEXT_REFRESH_TOKEN_123456789'),
                        expected_revision=first)
        with self.assertRaises(VaultError):
            self.store.save(self.id, credentials(), expected_revision=first)
        self.assertEqual(self.store.load(self.id).credentials['refresh_token'],
                         'FAKE_NEXT_REFRESH_TOKEN_123456789')

    def test_existing_lock_fails_closed(self):
        self.store._ensure_root()
        path = self.store._path(self.id)
        lock = path.with_suffix('.lock')
        lock.write_bytes(b'')
        with self.assertRaises(VaultError):
            self.store.save(self.id, credentials())
        self.assertTrue(lock.exists())  # stale lock remains for operator

    def test_tampered_ciphertext_rejected(self):
        self.store.save(self.id, credentials())
        path = self.store._path(self.id)
        path.write_bytes(b'CORRUPT')
        with self.assertRaises(VaultError):
            self.store.load(self.id)

    def test_read_dangling_symlink_rejected(self):
        self.store._ensure_root()
        path = self.store._path(self.id)
        try:
            path.symlink_to(self.root/'missing')
        except (OSError, NotImplementedError):
            self.skipTest('Symlink запрещён текущей платформой')
        with self.assertRaises(VaultError):
            self.store.load(self.id)

    def test_external_temp_link_does_not_get_overwritten(self):
        self.store.save(self.id, credentials())
        with self.assertRaises(VaultError):
            self.store.save(self.id, credentials(), expected_revision='x'*32)
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_invalid_credential_rejected_before_directory_creation(self):
        for field, bad in [('client_id','other'),('issuer','https://evil'),
                           ('token_type','Basic'), ('refresh_token',''),('saved_at',True),
                           ('scopes', ['openid','openid'])]:
            value = credentials()
            value[field] = bad
            with self.subTest(field=field), self.assertRaises(VaultError):
                self.store.save(self.id, value)
        self.assertFalse(self.root.exists())

    def test_bad_identity_is_rejected(self):
        with self.assertRaises(VaultError):
            self.store.save(None, credentials())

    def test_duplicate_json_field_rejected(self):
        blob = b'{"schema":"X","schema":"X","revision":"' + b'a'*32 + b'","credentials":{}}'
        with self.assertRaises(VaultError):
            _parse_envelope(blob, self.id)

    def test_unsafe_existing_root_refused(self):
        self.root.mkdir(parents=True)
        other = Path(self.tmp.name)/'other'
        other.mkdir()
        self.root.rmdir()
        try:
            self.root.symlink_to(other, target_is_directory=True)
        except (OSError,NotImplementedError):
            self.skipTest('Symlink недоступен')
        with self.assertRaises(VaultError):
            self.store.save(self.id, credentials())

    def test_atomic_failure_retains_original(self):
        rev = self.store.save(self.id, credentials())
        with patch('rai_fabric.credential_store.os.replace', side_effect=OSError('fake failure')):
            with self.assertRaises(VaultError) as ctx:
                self.store.save(self.id, credentials(refresh='FAKE_NEXT_REFRESH_TOKEN_123456789'),
                                expected_revision=rev)
        self.assertNotIn('fake failure', str(ctx.exception))
        self.assertEqual(self.store.load(self.id).revision, rev)
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_non_windows_public_vault_blocked(self):
        if os.name != 'nt':
            with self.assertRaises(VaultError):
                WindowsCredentialVault()


@unittest.skipUnless(os.name == 'nt', 'Нативное хранилище проверяется только под Windows')
class RealWindowsVaultTests(unittest.TestCase):
    def setUp(self):
        self.root = default_vault_root().parent / ('oauth_v1_test_' + uuid.uuid4().hex)
        self.vault = WindowsCredentialVault(root=self.root)
        self.id = identity()

    def tearDown(self):
        if self.root.exists():
            import shutil
            shutil.rmtree(self.root)

    def test_dpapi_file_acl_and_rotation(self):
        rev = self.vault.save(self.id, credentials())
        path = self.vault._path(self.id)
        self.vault._guard.verify(self.root)
        self.vault._guard.verify(path)
        self.assertEqual(self.vault.load(self.id).revision, rev)
        changed = credentials(refresh='FAKE_NEXT_REFRESH_TOKEN_123456789')
        next_rev = self.vault.save(self.id, changed, expected_revision=rev)
        self.assertNotEqual(next_rev, rev)
        self.assertEqual(self.vault.load(self.id).credentials['refresh_token'],
                         changed['refresh_token'])

    def test_windows_refresh_lock_has_acl_and_is_removed_after_success(self):
        self.vault.save(self.id, credentials())
        lock = self.vault._root / (self.vault._path(self.id).stem + '.refresh.lock')
        with self.vault.refresh_lock(self.id):
            self.assertTrue(lock.exists())
            self.vault._guard.verify(lock)
            with self.assertRaises(VaultError):
                with self.vault.refresh_lock(self.id):
                    pass
        self.assertFalse(lock.exists())

    def test_windows_refresh_lock_persists_after_uncertain_failure(self):
        self.vault.save(self.id, credentials())
        lock = self.vault._root / (self.vault._path(self.id).stem + '.refresh.lock')
        with self.assertRaises(RuntimeError):
            with self.vault.refresh_lock(self.id):
                raise RuntimeError('тест отказа внешнего провайдера')
        self.assertTrue(lock.exists())
        with self.assertRaises(VaultError):
            with self.vault.refresh_lock(self.id):
                pass

    def test_wrong_root_refused(self):
        with self.assertRaises(VaultError):
            WindowsCredentialVault(root=self.root.parent / 'unrelated')


if __name__ == '__main__':
    unittest.main()
