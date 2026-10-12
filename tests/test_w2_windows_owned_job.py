"""W2-C: negative и subtree checks для Windows Job Object synthetic worker."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from rai_fabric.store import FabricError
from rai_fabric.windows_owned_job import run_synthetic_job


class OwnedProcessContractTests(unittest.TestCase):
    def test_unsupported_mode_always_fail_closed(self):
        with self.assertRaises(FabricError):
            run_synthetic_job("NOT_ALLOWLISTED")

    def test_timeout_bounds_enforced(self):
        if sys.platform != "win32":
            with self.assertRaises(FabricError):
                run_synthetic_job("EXIT_ZERO", timeout_seconds=0.1)
        else:
            for seconds in (0.0, -1.0, 31.0):
                with self.subTest(seconds=seconds), self.assertRaises(FabricError):
                    run_synthetic_job("EXIT_ZERO", timeout_seconds=seconds)


@unittest.skipUnless(sys.platform == "win32", "Windows-only Job Objects")
class WindowsOwnedJobTests(unittest.TestCase):
    def test_owned_child_exits_and_no_descendants(self):
        with tempfile.TemporaryDirectory(prefix="raif-job-safe-") as folder:
            result = run_synthetic_job("EXIT_ZERO", timeout_seconds=8.0, cwd=folder)
        self.assertEqual(result["verdict"], "EXITED")
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["owned_job"])
        self.assertEqual(result["descendants_active"], 0)
        self.assertEqual(result["external_provider_calls"], 0)

    def test_child_exit_code_not_faked_as_success(self):
        result = run_synthetic_job("EXIT_NONZERO", timeout_seconds=8.0)
        self.assertEqual(result["verdict"], "EXITED")
        self.assertEqual(result["exit_code"], 7)
        self.assertEqual(result["descendants_active"], 0)

    def test_timeout_kills_only_owned_group(self):
        result = run_synthetic_job("HANG_PARENT", timeout_seconds=0.7)
        self.assertEqual(result["verdict"], "OWNED_GROUP_TERMINATED")
        self.assertEqual(result["descendants_active"], 0)

    def test_child_descendant_survives_parent_but_job_kills_it(self):
        result = run_synthetic_job("SPAWN_DESCENDANT", timeout_seconds=1.4)
        self.assertEqual(result["verdict"], "OWNED_GROUP_TERMINATED")
        self.assertEqual(result["descendants_active"], 0)

    def test_assignment_failure_terminates_suspended_owned_child(self):
        from unittest.mock import patch
        import rai_fabric.windows_owned_job as owned

        real = owned._kernel()

        class FaultInjectedKernel:
            terminate_calls = 0
            resume_calls = 0

            def __getattr__(self, key):
                if key == "AssignProcessToJobObject":
                    return lambda *_args: False
                if key == "ResumeThread":
                    def forbidden_resume(*_args):
                        self.resume_calls += 1
                        return 0xFFFFFFFF
                    return forbidden_resume
                if key == "TerminateProcess":
                    def terminate(handle, status):
                        self.terminate_calls += 1
                        return real.TerminateProcess(handle, status)
                    return terminate
                return getattr(real, key)

        fault = FaultInjectedKernel()
        with patch.object(owned, "_kernel", return_value=fault):
            with self.assertRaises(FabricError) as exc:
                run_synthetic_job("HANG_PARENT", timeout_seconds=1)
        self.assertEqual(str(exc.exception), "WINDOWS_JOB_ASSIGNMENT_REJECTED")
        self.assertEqual(fault.resume_calls, 0)
        self.assertGreaterEqual(fault.terminate_calls, 1)

    def test_missing_workspace_rejected_before_spawn(self):
        with tempfile.TemporaryDirectory() as folder:
            fake = Path(folder) / "absent"
            with self.assertRaises(FabricError):
                run_synthetic_job("EXIT_ZERO", cwd=fake)
            self.assertFalse(fake.exists())


if __name__ == "__main__":
    unittest.main()
