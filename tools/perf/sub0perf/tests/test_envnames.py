"""Tests for envnames: the SUB0PERF_* and SUB0MATH_* spellings of one variable agree."""

import unittest

from .. import envnames, hooks
from .helpers import RepoTestCase


class EnvNamesTest(unittest.TestCase):
    def test_a_new_name_alone_sets_the_old_one(self):
        env = envnames.apply_aliases({"SUB0PERF_SKIP": "why"})
        self.assertEqual(env["SUB0MATH_PERF_SKIP"], "why")

    def test_an_old_name_alone_sets_the_new_one(self):
        env = envnames.apply_aliases({"SUB0MATH_PERF_LEVEL": "full", "SUB0MATH_PINS_SKIP": "r"})
        self.assertEqual((env["SUB0PERF_LEVEL"], env["SUB0PERF_PINS_SKIP"]), ("full", "r"))

    def test_the_new_name_wins_when_both_are_given(self):
        env = envnames.apply_aliases({"SUB0PERF_BUDGET": "30", "SUB0MATH_PERF_BUDGET": "90"})
        self.assertEqual((env["SUB0PERF_BUDGET"], env["SUB0MATH_PERF_BUDGET"]), ("30", "30"))

    def test_unrelated_variables_are_untouched(self):
        env = envnames.apply_aliases({"PATH": "x"})
        self.assertEqual(env, {"PATH": "x"})

    def test_every_variable_the_tooling_reads_is_covered(self):
        from .. import baseline, power, speed
        for old in (baseline.HOST_VAR, hooks.MODE_VAR, power.OVERRIDE_VAR, power.STRICT_VAR, speed.LIMIT_VAR, speed.WARM_VAR):
            self.assertIn(old, [o for _, o in envnames.PAIRS])


class ToolingRecordTest(RepoTestCase):
    def test_either_record_name_finds_the_tooling(self):
        for name, where in ((hooks.TOOLING_RECORD, "build"), (hooks.OLD_TOOLING_RECORD, "build-old")):
            directory = self.repo / where
            directory.mkdir()
            (directory / name).write_text(str(self.repo / where / "tools"), encoding="utf-8")
        found = {str(p) for p in hooks.tooling_dirs(self.repo, environ={})}
        self.assertEqual(found, {str(self.repo / "build" / "tools"), str(self.repo / "build-old" / "tools")})


if __name__ == "__main__":
    unittest.main()
