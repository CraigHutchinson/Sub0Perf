"""Tests for hooks."""

import contextlib
import io
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from .. import gitstate
from ..common import read_json
from .. import hooks as hk
from .helpers import RepoTestCase, git_run


@unittest.skipUnless(shutil.which("sh"), "needs a POSIX sh")
class HooksTest(RepoTestCase):
    def install(self):
        args = type("A", (), {"repo": str(self.repo), "build_dir": str(self.repo / "build dir"), "target": "tgt",
                              "exe": str(self.repo / "build dir" / "tgt"), "baseline": str(self.repo / "b.json"), "config": ""})
        hk.install_hooks_command(args)
        return Path(gitstate.git(self.repo, "rev-parse", "--git-path", "hooks"))

    def hooks_dir(self):
        hooks = Path(gitstate.git(self.repo, "rev-parse", "--git-path", "hooks"))
        return hooks if hooks.is_absolute() else self.repo / hooks

    def run_hook(self, name, *args, stdin=""):
        return subprocess.run(["sh", str(self.hooks_dir() / name), *args], input=stdin, capture_output=True, text=True, cwd=self.repo)

    def test_hook_text_quotes_paths_with_spaces(self):
        body = hk.hook_body("pre-push", "C:/Program Files/Python/python.exe", "C:/my tools/bench_check.py", "x")
        self.assertIn("python='C:/Program Files/Python/python.exe'", body)
        self.assertIn("script='C:/my tools/bench_check.py'", body)

    def test_missing_tooling_makes_the_hook_a_no_op_with_a_message(self):
        hooks = self.hooks_dir()
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-push").write_text(hk.hook_body("pre-push", "/no/such/python", "/no/such/script.py", "x"), encoding="utf-8", newline="\n")
        result = self.run_hook("pre-push", "origin", "url", stdin="refs/heads/a " + "1" * 40 + " refs/heads/a " + "0" * 40 + "\n")
        self.assertEqual(result.returncode, 0)
        self.assertIn("missing", result.stdout)

    def test_install_creates_hooks_and_is_idempotent(self):
        self.install()
        first = (self.hooks_dir() / "pre-push").read_text(encoding="utf-8")
        self.install()
        self.assertEqual((self.hooks_dir() / "pre-push").read_text(encoding="utf-8"), first)
        self.assertIn(hk.HOOK_MARK, first)
        self.assertIn("--refs-from-stdin", first)
        self.assertTrue((self.hooks_dir() / "post-checkout").is_file())

    def test_reinstall_leaves_an_unchanged_running_hook_alone(self):
        self.install()
        original = hk.atomic_write_text

        def refuse_hooks(path, text):
            if Path(path).parent == self.hooks_dir():
                raise PermissionError("in use")  # what Windows does to a running hook
            original(path, text)

        hk.atomic_write_text = refuse_hooks
        try:
            self.install()  # unchanged hooks are skipped, so nothing is replaced
            (self.hooks_dir() / "pre-push").write_text("# stale ours " + hk.HOOK_MARK + "\n", encoding="utf-8")
            self.install()  # a changed one that cannot be replaced is reported, not raised
        finally:
            hk.atomic_write_text = original

    def test_foreign_hook_is_kept_and_chained_with_stdin_and_arguments(self):
        hooks = self.hooks_dir()
        hooks.mkdir(parents=True, exist_ok=True)
        out = self.repo / "seen.txt"
        (hooks / "pre-push").write_text(f'#!/bin/sh\necho "args=$@" > "{out.as_posix()}"\ncat >> "{out.as_posix()}"\n',
                                         encoding="utf-8", newline="\n")
        (hooks / "pre-push").chmod(0o755)  # a real hook is executable; git and the chain run it directly
        self.install()
        self.assertTrue((hooks / "pre-push.user").is_file())
        self.assertIn(hk.HOOK_MARK, (hooks / "pre-push").read_text(encoding="utf-8"))
        # The user's hook runs first with the arguments and stdin; ours then refuses (the pushed sha is not HEAD).
        result = self.run_hook("pre-push", "origin", "url", stdin="refs/heads/a " + "1" * 40 + " refs/heads/a " + "0" * 40 + "\n")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("push refused", result.stdout)
        seen = out.read_text(encoding="utf-8")
        self.assertIn("args=origin url", seen)
        self.assertIn("refs/heads/a", seen)

    def test_failing_user_hook_stops_the_push(self):
        hooks = self.hooks_dir()
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-push").write_text("#!/bin/sh\nexit 3\n", encoding="utf-8", newline="\n")
        (hooks / "pre-push").chmod(0o755)
        self.install()
        self.assertEqual(self.run_hook("pre-push", "origin", "url").returncode, 3)

@unittest.skipUnless(shutil.which("sh"), "needs a POSIX sh")
class TrackedHooksTest(RepoTestCase):
    """core.hooksPath inside the worktree (.githooks): committed files, never renamed or overwritten; ours are chained by one line."""

    def setUp(self):
        super().setUp()
        (self.repo / "f.txt").write_text("one", encoding="utf-8")
        git_run(self.repo, "add", ".")
        git_run(self.repo, "commit", "-q", "-m", "one")
        git_run(self.repo, "config", "core.hooksPath", ".githooks")
        self.tracked = self.repo / ".githooks"
        self.tracked.mkdir()

    def install(self, mode=None):
        args = type("A", (), {"repo": str(self.repo), "build_dir": str(self.repo / "build"), "target": "tgt",
                              "exe": str(self.repo / "build" / "tgt"), "baseline": str(self.repo / "b.json"), "config": ""})
        env = {hk.MODE_VAR: mode} if mode else {}
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out):
            hk.install_hooks_command(args)
        return out.getvalue()

    def committed_hook(self, text="#!/bin/sh\necho committed\n"):
        path = self.tracked / "pre-push"
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def plain_hooks_dir(self):
        found = Path(gitstate.git(self.repo, "rev-parse", "--git-path", "hooks"))
        return found if found.is_absolute() else self.repo / found

    def test_a_tracked_directory_is_detected(self):
        self.assertTrue(hk.is_tracked_dir(self.repo))
        git_run(self.repo, "config", "core.hooksPath", str(Path(self.tmp.name) / "outside"))
        self.assertFalse(hk.is_tracked_dir(self.repo))
        git_run(self.repo, "config", "--unset", "core.hooksPath")
        self.assertFalse(hk.is_tracked_dir(self.repo))

    def test_a_committed_hook_is_neither_renamed_nor_overwritten(self):
        path = self.committed_hook()
        before = path.read_text(encoding="utf-8")
        text = self.install()
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        self.assertEqual(sorted(p.name for p in self.tracked.iterdir()), ["pre-push"])  # no pre-push.user, no post-checkout
        self.assertIn("left pre-push alone", text)
        self.assertIn(hk.chain_line("pre-push"), text)

    def test_nothing_is_written_to_a_tracked_directory_that_has_no_hook(self):
        text = self.install()
        self.assertEqual(list(self.tracked.iterdir()), [])
        self.assertIn("left pre-push alone", text)

    def test_ours_are_kept_in_git_sub0perf_and_the_printed_line_runs_the_gate(self):
        path = self.committed_hook()
        self.install()
        chained = hk.chain_path(self.repo, "pre-push")
        self.assertTrue(chained.is_file())
        self.assertIn(hk.HOOK_MARK, chained.read_text(encoding="utf-8"))
        path.write_text("#!/bin/sh\n" + hk.chain_line("pre-push") + "\necho committed\n", encoding="utf-8", newline="\n")
        # The one line, in the committed hook, runs ours (which refuses a pushed sha that is not HEAD), and stops the push.
        result = subprocess.run(["sh", str(path), "origin", "url"], input="refs/heads/a " + "1" * 40 + " refs/heads/a " + "0" * 40 + "\n",
                                capture_output=True, text=True, cwd=self.repo)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("push refused", result.stdout)
        self.assertNotIn("committed", result.stdout)

    def test_once_the_line_is_in_the_hook_nothing_more_is_printed_for_it(self):
        text_in = "#!/bin/sh\n" + hk.chain_line("pre-push") + "\n"
        path = self.committed_hook(text_in)
        text = self.install()
        self.assertNotIn("pre-push alone", text)
        self.assertIn("post-checkout", text)  # that one has no line yet
        self.assertEqual(path.read_text(encoding="utf-8"), text_in)

    def test_chain_mode_leaves_even_an_untracked_hooks_directory_alone(self):
        git_run(self.repo, "config", "--unset", "core.hooksPath")
        hooks = self.plain_hooks_dir()
        text = self.install(mode="chain")
        self.assertFalse((hooks / "pre-push").exists())
        self.assertTrue(hk.chain_path(self.repo, "pre-push").is_file())
        self.assertIn("chain", text)

    def test_an_unknown_mode_is_said_and_ignored(self):
        git_run(self.repo, "config", "--unset", "core.hooksPath")
        text = self.install(mode="bogus")
        self.assertIn("not install or chain", text)
        self.assertIn(hk.HOOK_MARK, (self.plain_hooks_dir() / "pre-push").read_text(encoding="utf-8"))

    def test_the_default_mode_still_installs_in_an_untracked_directory(self):
        git_run(self.repo, "config", "--unset", "core.hooksPath")
        self.install()
        self.assertIn(hk.HOOK_MARK, (self.plain_hooks_dir() / "pre-push").read_text(encoding="utf-8"))




@unittest.skipUnless(shutil.which("sh"), "needs a POSIX sh")
class LinkedWorktreeTest(RepoTestCase):
    """The hooks and .git/sub0perf are shared by every worktree: only the main checkout writes them."""

    def setUp(self):
        super().setUp()
        (self.repo / "a.txt").write_text("a", encoding="utf-8")
        git_run(self.repo, "add", "a.txt")
        git_run(self.repo, "commit", "-q", "-m", "one")
        self.linked = Path(self.tmp.name) / "linked"
        git_run(self.repo, "worktree", "add", "-q", str(self.linked), "-b", "side")

    def args(self, repo, build_dir, **extra):
        values = {"repo": str(repo), "build_dir": str(build_dir), "target": "tgt", "exe": str(build_dir / "tgt"),
                  "baseline": str(repo / "b.json"), "config": ""}
        values.update(extra)
        return type("A", (), values)

    def install(self, args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            hk.install_hooks_command(args)
        return out.getvalue()

    def test_a_linked_worktree_is_recognised(self):
        self.assertTrue(gitstate.is_linked_worktree(self.linked))
        self.assertFalse(gitstate.is_linked_worktree(self.repo))

    def test_install_from_a_linked_worktree_refuses_in_one_line_and_writes_nothing(self):
        text = self.install(self.args(self.linked, self.linked / "build"))
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertIn("main checkout", text)
        self.assertFalse((gitstate.perf_dir(self.repo) / "config.json").exists())
        self.assertFalse((hk.hooks_dir(self.repo) / "pre-push").exists())
        self.assertIsNone(gitstate.git(self.repo, "config", "--get", "core.hooksPath"))

    def test_an_absolute_hooks_path_into_the_main_checkout_is_tracked_from_a_linked_worktree(self):
        (self.repo / ".githooks").mkdir()
        git_run(self.repo, "config", "core.hooksPath", str(self.repo / ".githooks"))
        self.assertTrue(hk.is_tracked_dir(self.repo))
        self.assertTrue(hk.is_tracked_dir(self.linked))

    def test_the_default_hooks_directory_is_not_tracked(self):
        self.assertFalse(hk.is_tracked_dir(self.repo))
        self.assertFalse(hk.is_tracked_dir(self.linked))

    def test_a_second_build_directory_leaves_the_gate_alone_while_the_first_exists(self):
        first, second = self.repo / "build", self.repo / "build-local"
        first.mkdir()
        second.mkdir()
        self.install(self.args(self.repo, first))
        text = self.install(self.args(self.repo, second, keep_existing=True))
        self.assertIn(str(first), text)
        config = read_json(gitstate.perf_dir(self.repo) / "config.json")
        self.assertEqual(config["targets"]["tgt"]["build_dir"], str(first.resolve()))

    def test_taking_over_and_a_vanished_first_directory_repoint_the_gate(self):
        first, second = self.repo / "build", self.repo / "build-local"
        first.mkdir()
        second.mkdir()
        self.install(self.args(self.repo, first))
        self.install(self.args(self.repo, second))  # no keep_existing: ON, or a hand-run install-hooks
        config = read_json(gitstate.perf_dir(self.repo) / "config.json")
        self.assertEqual(config["targets"]["tgt"]["build_dir"], str(second.resolve()))
        first.rmdir()
        third = self.repo / "build-3"
        third.mkdir()
        second.rmdir()
        self.install(self.args(self.repo, third, keep_existing=True))
        config = read_json(gitstate.perf_dir(self.repo) / "config.json")
        self.assertEqual(config["targets"]["tgt"]["build_dir"], str(third.resolve()))

    def test_the_gate_names_the_fix_for_a_missing_or_foreign_build_directory(self):
        from .. import gate
        missing = gate.target_problem(self.repo, {"build_dir": str(self.repo / "gone")})
        self.assertIn("reconfigure", missing)
        (self.linked / "build").mkdir()
        foreign = gate.target_problem(self.repo, {"build_dir": str(self.linked / "build")})
        self.assertIn("another worktree", foreign)
        (self.repo / "build").mkdir()
        self.assertIsNone(gate.target_problem(self.repo, {"build_dir": str(self.repo / "build")}))
        self.assertIn("another worktree", gate.target_problem(self.linked, {"build_dir": str(self.repo / "build")}))

    def test_temporary_repositories_do_not_inherit_the_hooks_git_dir(self):
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            self.assertNotIn(name, os.environ)
