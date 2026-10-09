"""Тесты планирования Windows vault и настоящего DPAPI с тестовым BLOB."""
import os
import unittest
from rai_fabric.windows_vault import (
    CRYPTPROTECT_UI_FORBIDDEN, VaultError, WindowsUserDPAPI,
    credential_record_key, default_vault_root,
)


class VaultPlanTests(unittest.TestCase):
    def test_stable_private_record_name(self):
        key = credential_record_key(client_id='oaiapp_offline', subject='private-sub')
        self.assertEqual(len(key), 64)
        self.assertNotIn('private-sub', key)
        self.assertEqual(key, credential_record_key(client_id='oaiapp_offline', subject='private-sub'))
        self.assertNotEqual(key, credential_record_key(client_id='oaiapp_another', subject='private-sub'))
        self.assertNotEqual(key, credential_record_key(client_id='oaiapp_offline', subject='other-sub'))

    def test_unissued_client_and_bad_identity_blocked(self):
        for client, sub in [('dynamic_agent_client','real'),('', 'real'),('valid',''),('', '')]:
            with self.assertRaises(VaultError):
                credential_record_key(client_id=client, subject=sub)

    def test_no_linux_vault_or_dpapi(self):
        if os.name != 'nt':
            with self.assertRaises(VaultError):
                default_vault_root()
            with self.assertRaises(VaultError):
                WindowsUserDPAPI()

    def test_never_encrypt_for_all_machine_users(self):
        self.assertEqual(CRYPTPROTECT_UI_FORBIDDEN, 1)
        self.assertFalse(hasattr(WindowsUserDPAPI, 'encrypt_for_machine'))


@unittest.skipUnless(os.name == 'nt', 'Windows DPAPI используется только на Windows')
class RealWindowsDpapiTests(unittest.TestCase):
    def test_roundtrip_with_nonsecret_test_bytes(self):
        api = WindowsUserDPAPI()
        synthetic = b'OFFLINE_FAKE_CREDENTIAL_123\x00not_a_real_token'
        encrypted = api.protect(synthetic)
        self.assertNotEqual(encrypted, synthetic)
        self.assertNotIn(synthetic, encrypted)
        self.assertEqual(api.unprotect(encrypted), synthetic)

    def test_corruption_and_invalid_size_blocked(self):
        api = WindowsUserDPAPI()
        for bad in (b'', b'x' * (1024*1024+1)):
            with self.assertRaises(VaultError):
                api.protect(bad)
        # Не утверждаем, что любая случайная порча всегда вызывает ошибку:
        # формат DPAPI может содержать нерелевантные поля. Чужой BLOB отклоняем.
        with self.assertRaises(VaultError):
            api.unprotect(b'NOT_A_DPAPI_PROTECTED_BLOB')

    def test_windows_vault_root_is_under_local_appdata(self):
        directory = default_vault_root()
        self.assertIn('Rassvet_AI_Fabric', directory.parts)
        self.assertTrue(directory.is_absolute())


if __name__=='__main__': unittest.main()
