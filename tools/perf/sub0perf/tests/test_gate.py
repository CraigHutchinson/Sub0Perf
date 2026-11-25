"""Tests for gate."""

import json
import os
import sys
import unittest

from .. import common, gate, gitstate
from .helpers import git_run, RepoTestCase


class GateSkipTest(RepoTestCase):
    def test_skip_bypasses_and_is_logged(self):
        git_run(self.repo, "commit", "-q", "--allow-empty", "-m", "one")
        args = type("A", (), {"repo": str(self.repo)})
        os.environ["SUB0PERF_SKIP"] = "emergency fix"
        try:
            self.assertEqual(gate.gate_command(args), 0)
        finally:
            del os.environ["SUB0PERF_SKIP"]
        log = (gitstate.perf_dir(self.repo) / "log.jsonl").read_text(encoding="utf-8")
        self.assertIn("emergency fix", log)
        self.assertIn('"skip"', log)


class GateRefusalTest(RepoTestCase):
    """The gate's push checks run before any build: a configured repository with no targets shows them."""

    def setUp(self):
        super().setUp()
        (self.repo / "f.txt").write_text("one", encoding="utf-8")
        git_run(self.repo, "add", ".")
        git_run(self.repo, "commit", "-q", "-m", "one")
        self.head = gitstate.git_head(self.repo)
        common.atomic_write_text(gitstate.perf_dir(self.repo) / "config.json", json.dumps({"targets": {}}))

    def gate(self, stdin_text):
        import io
        args = type("A", (), {"repo": str(self.repo), "refs_from_stdin": True, "lock_timeout": 1.0})
        real = sys.stdin
        sys.stdin = io.StringIO(stdin_text)
        try:
            return gate.gate_command(args)
        finally:
            sys.stdin = real

    def push(self, sha):
        return f"refs/heads/main {sha} refs/heads/main {'0' * 40}\n"

    def test_clean_pushed_head_proceeds(self):
        self.assertEqual(self.gate(self.push(self.head)), 0)

    def test_dirty_tree_is_refused_and_logged(self):
        (self.repo / "f.txt").write_text("two", encoding="utf-8")
        self.assertEqual(self.gate(self.push(self.head)), 1)
        self.assertIn("gate-refused", (gitstate.perf_dir(self.repo) / "log.jsonl").read_text(encoding="utf-8"))

    def test_untracked_files_do_not_refuse(self):
        (self.repo / "new.txt").write_text("x", encoding="utf-8")
        self.assertEqual(self.gate(self.push(self.head)), 0)

    def test_pushing_another_commit_is_refused(self):
        git_run(self.repo, "commit", "-q", "--allow-empty", "-m", "two")
        self.assertEqual(self.gate(self.push(self.head)), 1)  # HEAD moved on; the pushed sha is the older commit

    def test_deleting_a_branch_proceeds_even_when_dirty(self):
        (self.repo / "f.txt").write_text("two", encoding="utf-8")
        self.assertEqual(self.gate(self.push("0" * 40)), 0)

    def test_nothing_pushed_measures_nothing(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(self.gate(""), 0)  # git runs the hook with no refs when everything is up to date
        self.assertIn("nothing is pushed", out.getvalue())


class StaleBaselineHintTest(unittest.TestCase):
    """Rows moving both ways against the baseline, but not against the previous commit's record, say the baseline is out of date."""

    def rows(self, improved):
        return [("r%d" % i, 0, 0, 0, 0, "IMPROVED") for i in range(improved)] + [("slow", 0, 0, 0, 0, "REGRESSED")]

    def test_improvements_beside_regressions_with_a_clean_record_hint_at_a_stale_baseline(self):
        text = gate.stale_baseline_hint(self.rows(3), True, False, "abcdef0123456")
        self.assertIn("out of date", text)
        self.assertIn("abcdef012", text)
        self.assertIn("3 row(s) improved", text)

    def test_no_hint_without_a_record_with_a_regression_against_it_or_with_few_improvements(self):
        self.assertEqual(gate.stale_baseline_hint(self.rows(3), False, False, "abc"), "")
        self.assertEqual(gate.stale_baseline_hint(self.rows(3), True, True, "abc"), "")  # this push regressed against the record
        self.assertEqual(gate.stale_baseline_hint(self.rows(2), True, False, "abc"), "")
