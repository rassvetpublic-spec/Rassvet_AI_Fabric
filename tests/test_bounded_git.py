"""Synthetic bounded Git output/timeout/encoding QA for 10.1F.

These tests substitute a local Python child for the Git executable: zero remote
calls, credentials, Git mutations, or user-provided test executables. They are
independent of the Windows-only worktree integration test suite.
"""
import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

# Supports execution from a checked-out repo or via explicit package staging.
SOURCE = Path(__file__).resolve().parents[1] / 'src' / 'rai_fabric' / 'worktree_review.py'
spec = importlib.util.spec_from_file_location('raif_10_1f_worktree_review', SOURCE)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)
REAL_POPEN = subprocess.Popen


class BoundedGitSyntheticTests(unittest.TestCase):
    """Local process tests exercising the actual candidate _git implementation."""

    def invoke(self, script, *, timeout=4):
        child = [sys.executable, '-I', '-X', 'utf8', '-c', script]
        launched = []
        def child_factory(_git_argv, **kwargs):
            self.assertFalse(kwargs.get('shell', True))
            self.assertIs(kwargs.get('stderr'), subprocess.DEVNULL)
            self.assertIs(kwargs.get('stdin'), subprocess.DEVNULL)
            self.assertEqual(kwargs['env'].get('GIT_TERMINAL_PROMPT'), '0')
            self.assertEqual(kwargs['env'].get('GIT_NO_LAZY_FETCH'), '1')
            proc = REAL_POPEN(child, **kwargs)
            launched.append(proc)
            return proc
        with mock.patch.object(subject.subprocess, 'Popen', side_effect=child_factory):
            try:
                value = subject._git(Path.cwd(), 'status', '--porcelain', timeout=timeout)
                return ('OK', value, launched)
            except subject.ReviewBlocked as e:
                return (e.code, None, launched)
            finally:
                self.assertEqual(len(launched), 1)
                self.assertIsNotNone(launched[0].poll(), 'Child process must be reaped')

    def test_small_LF_binary_exact(self):
        status, data, _ = self.invoke("import sys; sys.stdout.buffer.write(b'OK\\n')")
        self.assertEqual((status, data), ('OK', b'OK\n'))

    def test_small_CRLF_binary_exact(self):
        status, data, _ = self.invoke("import sys; sys.stdout.buffer.write(b'OK\\r\\n')")
        self.assertEqual((status, data), ('OK', b'OK\r\n'))

    def test_non_utf8_bytes_not_text_decoded(self):
        status, data, _ = self.invoke("import sys; sys.stdout.buffer.write(bytes([0xff,0x00,0x98]))")
        self.assertEqual((status, data), ('OK', b'\xff\x00\x98'))

    def test_output_overflow_fails_before_unbounded_capture(self):
        status, data, _ = self.invoke("import sys; sys.stdout.buffer.write(b'X'*(4*1024*1024));sys.stdout.buffer.flush()")
        self.assertEqual(status, 'GIT_OUTPUT_LIMIT')
        self.assertIsNone(data)

    def test_output_at_exact_boundary_accepted(self):
        length = subject.MAX_PATCH_BYTES + 64*1024
        status, data, _ = self.invoke(f"import sys;sys.stdout.buffer.write(b'Y'*{length})")
        self.assertEqual(status, 'OK')
        self.assertEqual(len(data), length)

    def test_one_extra_byte_is_rejected(self):
        length = subject.MAX_PATCH_BYTES + 64*1024 + 1
        status, _, _ = self.invoke(f"import sys;sys.stdout.buffer.write(b'Z'*{length})")
        self.assertEqual(status, 'GIT_OUTPUT_LIMIT')

    def test_timeout_kills_and_reaps_process(self):
        status, _, p = self.invoke("import time;time.sleep(8)", timeout=0.35)
        self.assertEqual(status, 'GIT_NOT_AVAILABLE_OR_TIMEOUT')
        self.assertIsNotNone(p[0].poll())

    def test_nonzero_exit_rejected(self):
        status, _, _ = self.invoke('import sys;sys.exit(7)')
        self.assertEqual(status, 'GIT_COMMAND_REJECTED')

    def test_stderr_discarded(self):
        status, data, _ = self.invoke("import sys;sys.stderr.write('SECRET DO NOT LOG\\n');sys.stdout.buffer.write(b'SAFE')")
        self.assertEqual((status, data), ('OK', b'SAFE'))

    def test_environment_git_prefix_stripped(self):
        with mock.patch.dict(os.environ, {'GIT_TEST_UNSAFE':'SENTINEL'}, clear=False):
            status, data, _ = self.invoke("import os,sys;sys.stdout.buffer.write(b'BAD' if os.getenv('GIT_TEST_UNSAFE') else b'CLEAN')")
        self.assertEqual((status, data), ('OK', b'CLEAN'))


if __name__ == '__main__':
    unittest.main()
