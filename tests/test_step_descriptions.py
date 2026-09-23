"""Every step the dashboard can name has a plain-language description, and the
server publishes them with the history (`startup_model.step_descriptions`)."""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from swagperf import budgets, derive, server, store
from swagperf.extract import extract
from swagperf.synth import gen_trace


def _every_step_name():
    names = {name for name, _ in derive.PHASES}
    names |= set(budgets.STEP_RUNTIME) | set(budgets.STEP_BUDGETS_MS) | set(budgets.DEFERRED_STEPS)
    names |= set(budgets.CRITICAL_PATH_RETURNING) | set(budgets.CRITICAL_PATH_FIRST_RUN)
    return names


class TestStepDescriptions(unittest.TestCase):

    def test_every_step_has_a_description(self):
        missing = sorted(n for n in _every_step_name() if not budgets.STEP_DESCRIPTIONS.get(n, "").strip())
        self.assertEqual(missing, [], "add these to STEP_DESCRIPTIONS in swagperf/budgets.py")

    def test_no_description_for_a_step_that_does_not_exist(self):
        self.assertEqual(sorted(set(budgets.STEP_DESCRIPTIONS) - _every_step_name()), [])

    def test_descriptions_are_short_plain_sentences(self):
        for name, text in budgets.STEP_DESCRIPTIONS.items():
            self.assertLessEqual(len(text.split()), 40, name)
            self.assertTrue(text.endswith("."), name)
            self.assertNotIn("RSS", text, name)
            self.assertNotIn("  ", text, f"{name}: doubled space from string joining")

    def test_the_server_publishes_them_beside_the_runtimes(self):
        db = os.path.join(tempfile.mkdtemp(), "h.db")
        data, _ = gen_trace(seed=1)
        path = os.path.join(os.path.dirname(db), "t.pftrace")
        with open(path, "wb") as fh:
            fh.write(data)
        store.record(extract(path), device="V2514", db=db)
        orig = store.DB
        store.DB = db
        try:
            model = server._payload()["startup_model"]
        finally:
            store.DB = orig
        self.assertEqual(model["step_descriptions"], budgets.STEP_DESCRIPTIONS)
        self.assertEqual(model["step_runtime"], budgets.STEP_RUNTIME)
        for name in _every_step_name():
            self.assertIn(name, model["step_descriptions"])


if __name__ == "__main__":
    unittest.main()
