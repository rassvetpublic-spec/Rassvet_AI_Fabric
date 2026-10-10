"""Single-machine advisory lock tests; no user data or network."""
import tempfile
import unittest
from pathlib import Path

from raif_ag_supervisor.filelock import RegistryBusyError, exclusive_file_lock
from raif_ag_supervisor.registry import LocalAccountRegistry
from raif_ag_supervisor.vault import InMemoryTestVault


class FileLockTests(unittest.TestCase):
    def test_exclusive_lock_fails_closed_on_second_acquisition(self):
        with tempfile.TemporaryDirectory(prefix="raif-lock-") as directory:
            lock_file = Path(directory) / ".registry.lock"
            with exclusive_file_lock(lock_file):
                with self.assertRaises(RegistryBusyError):
                    with exclusive_file_lock(lock_file):
                        self.fail("lock must not allow concurrent writers")
            with exclusive_file_lock(lock_file):
                pass

    def test_recovery_cannot_modify_a_locked_registry(self):
        with tempfile.TemporaryDirectory(prefix="raif-lock-") as directory:
            registry = LocalAccountRegistry(Path(directory))
            with exclusive_file_lock(registry.root / ".registry.lock"):
                with self.assertRaises(RegistryBusyError):
                    registry.recover(InMemoryTestVault())


if __name__ == "__main__":
    unittest.main()
