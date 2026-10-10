import unittest
from raif_ag_supervisor import Account, Supervisor, State

class TestSupervisor(unittest.TestCase):
    def setUp(self):
        self.s = Supervisor([Account("a"), Account("b")])
        self.s.start("a", "CP-10:1")

    def test_429_plans_but_does_not_swap(self):
        self.s.observe_error(429)
        self.assertEqual(self.s.plan_handoff(), "b")
        self.assertEqual(self.s.active_id, "a")
        self.assertEqual(self.s.state, State.NEEDS_HANDOFF)

    def test_401_and_403_do_not_rotate(self):
        for code in (401, 403):
            with self.subTest(code=code):
                s = Supervisor([Account("a"), Account("b")])
                s.start("a", "stage")
                s.observe_error(code)
                self.assertEqual(s.state, State.BLOCKED)
                self.assertEqual(s.active_id, "a")

    def test_handoff_requires_validation(self):
        self.s.observe_error(429)
        with self.assertRaises(RuntimeError):
            self.s.confirm_handoff("b", False)
        self.s.confirm_handoff("b", True)
        self.assertEqual(self.s.state, State.READY_TO_RESUME)
        self.assertEqual(self.s.cursor, "CP-10:1")

    def test_no_candidates(self):
        s = Supervisor([Account("a"), Account("b", quota_available=False)])
        s.start("a", "cursor")
        s.observe_error(429)
        self.assertIsNone(s.plan_handoff())
        self.assertEqual(s.state, State.BLOCKED)

    def test_checkpoint_has_no_secrets(self):
        data = self.s.checkpoint()
        self.assertEqual(data["cursor"], "CP-10:1")
        self.assertNotIn("token", str(data).lower())

if __name__ == "__main__":
    unittest.main()
