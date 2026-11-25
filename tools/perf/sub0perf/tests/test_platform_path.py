"""Tests for platform_path: finding Sub0Platform's python/ directory without installing it."""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from .. import platform_path as pp
from .helpers import RepoTestCase, git_run


def fake_package(root):
    package = Path(root) / "python" / "sub0platform"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    return str(Path(root) / "python")


class PlatformPathTest(RepoTestCase):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(sys, "path", list(sys.path))
        patch.start()
        self.addCleanup(patch.stop)
        # pretend sub0platform is not importable, whatever the host has
        patch = mock.patch.object(pp.importlib.util, "find_spec", return_value=None)
        patch.start()
        self.addCleanup(patch.stop)
        self.package = fake_package(Path(self.tmp.name) / "plat")

    def test_already_importable_adds_nothing(self):
        with mock.patch.object(pp.importlib.util, "find_spec", return_value=object()):
            self.assertIsNone(pp.ensure(self.repo, {}))

    def test_the_environment_variable_is_first(self):
        self.assertEqual(pp.ensure(self.repo, {pp.ENV_VAR: self.package}), self.package)
        self.assertEqual(sys.path[0], self.package)

    def test_the_git_config_is_found_from_a_hook(self):
        git_run(self.repo, "init", "-q")
        directory = self.repo / ".git" / "sub0perf"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "config.json").write_text(json.dumps({"platform_python": self.package}), encoding="utf-8")
        self.assertEqual(pp.ensure(self.repo, {}), self.package)

    def test_the_build_record_is_found(self):
        build = self.repo / "build" / "debug"
        build.mkdir(parents=True)
        (build / pp.RECORD).write_text(self.package + "\n", encoding="utf-8")
        self.assertEqual(pp.ensure(self.repo, {}), self.package)

    def test_a_stale_record_is_skipped_for_a_valid_one(self):
        old, new = self.repo / "build-old", self.repo / "build-new"
        for build, target in ((old, "/no/such/dir"), (new, self.package)):
            build.mkdir()
            (build / pp.RECORD).write_text(target, encoding="utf-8")
        self.assertEqual(pp.ensure(self.repo, {}), self.package)

    def test_nothing_found_says_how_to_fix_it(self):
        with self.assertRaises(ImportError) as error:
            pp.ensure(self.repo, {})
        self.assertIn(pp.ENV_VAR, str(error.exception))
        self.assertIn("Configure the build", str(error.exception))

    def test_install_hooks_records_the_platform_directory(self):
        from .. import hooks
        args = type("A", (), {"repo": str(self.repo), "build_dir": str(self.repo / "b"), "target": "t", "exe": str(self.repo / "b" / "t"),
                              "baseline": str(self.repo / "x.json"), "config": "", "platform_dir": self.package})
        (self.repo / "b").mkdir()
        hooks.install_hooks_command(args)
        config = json.loads((self.repo / ".git" / "sub0perf" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(config["platform_python"]), Path(self.package).resolve())


if __name__ == "__main__":
    unittest.main()
