import contextlib
import io
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from .. import cli, deferral, machine, output, selftest, workload


class MachinePolicyTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.lease = machine.platform_lease()
        default = mock.patch.object(self.lease, "defaultLockFile", return_value=self.root / "fixture.machine.lock")
        default.start()
        self.addCleanup(default.stop)

    def test_wait_budgets_and_deduplicated_owner_announcement(self):
        owner = self.lease.LeaseOwner(123, 0.0, "serving", "fixture", "shared")
        for options, limit in (({}, 900), ({"pre_push": True}, 120), ({"no_wait": True}, 0)):
            def simulate(mode, tool, what, *, timeout, onWait):
                self.assertEqual((mode, tool, what, timeout), ("exclusive", "sub0perf", "test", limit))
                if timeout:
                    onWait([owner])
                    onWait([owner])
                return None

            with mock.patch.object(self.lease, "acquire", side_effect=simulate), \
                 mock.patch.object(self.lease, "readOwners", return_value=[owner]), \
                 contextlib.redirect_stderr(io.StringIO()) as stderr, self.assertRaises(machine.Busy) as blocked:
                machine.take("test", **options)
            self.assertEqual(blocked.exception.blocked()["wait_seconds"], limit)
            self.assertEqual(stderr.getvalue().count("held by fixture"), int(bool(limit)))

    def test_no_wait_keeps_existing_auto_and_compare_outcome_paths(self):
        outcome_file = self.root / "outcome.json"
        with self.lease.acquire("shared", "fixture", "serve"):
            for command in ("auto", "compare"):
                with self.subTest(command=command):
                    argv = ["bench_check.py", command, "--exe", "bench", "--baseline", "base", "--no-wait",
                            "--format", "json", "--out-json", str(outcome_file), "--report", str(self.root / "report.md")]
                    with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()) as stdout:
                        result = cli.main()
                    data = json.loads(stdout.getvalue())
                    self.assertEqual((result, data["schema"], data["status"]), (1, output.OUTCOME_SCHEMA, "BLOCKED"))
                    self.assertEqual(data["blocked"]["holders"][0]["tool"], "fixture")
                    self.assertEqual(data, json.loads(outcome_file.read_text(encoding="utf-8")))

    def test_late_deferral_survives_clearing_the_ranges_a_gate_covered(self):
        deferral.add(self.root, "a" * 40, [], "first")
        covered = deferral.load(self.root)
        deferral.add(self.root, "b" * 40, [], "while gate was already running")
        deferral.clear(self.root, covered)
        self.assertEqual([entry["head"] for entry in deferral.load(self.root)], ["b" * 40])

    def test_raw_target_preserves_exit_status_and_holds_lease_during_the_command(self):
        code = "import sys; from sub0platform import lease; held = lease.acquire('shared', 'child', 'probe', lockFile=sys.argv[1]); sys.exit(0 if held is None else 2)"
        path = self.lease.defaultLockFile()
        command = ["--no-wait", "--", sys.executable, "-c", code, str(path)]
        with self.lease.acquire("shared", "fixture", "serve"), contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(cli.timed_exec(command), 1)
        self.assertIn("held by fixture", stdout.getvalue())
        with mock.patch.dict(os.environ, {"PYTHONPATH": str(Path(self.lease.__file__).parents[1])}):
            self.assertEqual(cli.timed_exec(command), 0)

    def test_workload_keeps_its_outcome_schema_when_the_machine_is_busy(self):
        spec = self.root / "spec.json"
        spec.write_text(json.dumps({"identity": {"fixture": "example"}, "inputs": {"input": "spec.json"},
                                   "command": [sys.executable, "-c", "pass"],
                                   "correctness": [sys.executable, "-c", "pass"], "cache": "uncontrolled"}), encoding="utf-8")
        result = self.root / "result.json"
        with self.lease.acquire("shared", "fixture", "serve"), mock.patch.object(workload, "git_head", return_value="a" * 40), \
             mock.patch.object(workload, "execute", side_effect=AssertionError("busy work must not run")), \
             contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = workload.main(["measure", "--spec", str(spec), "--repo", str(self.root),
                                  "--out", str(result), "--no-wait"])
        data = json.loads(stdout.getvalue())
        self.assertEqual((code, data["schema"], data["status"]), (1, "sub0perf-workload-outcome-1", "refused"))
        self.assertEqual(data["blocked"]["holders"][0]["tool"], "fixture")
        self.assertFalse(result.exists())

    def test_deferred_commits_are_covered_only_by_a_gate_build_containing_them(self):
        deferral.add(self.root, "a" * 40, [], "on this branch")
        deferral.add(self.root, "b" * 40, [], "on a different branch")

        def ancestor(repo, operation, flag, candidate, head):
            self.assertEqual((repo, operation, flag, head), (self.root, "merge-base", "--is-ancestor", "c" * 40))
            return "" if candidate == "a" * 40 else None

        with mock.patch.object(deferral, "git", side_effect=ancestor):
            covered = deferral.covered(self.root, self.root, "c" * 40)
        deferral.clear(self.root, covered)
        self.assertEqual([entry["head"] for entry in deferral.load(self.root)], ["b" * 40])

    def test_selftest_reports_busy_and_skips_optional_calibration(self):
        exe = self.root / "test-executable"
        exe.touch()
        config = {"targets": {"fixture": {"exe": str(exe), "baseline": "baseline.json"}}}
        with self.lease.acquire("shared", "fixture", "serve"), \
             mock.patch.object(selftest.speed, "check_targets", side_effect=AssertionError("busy calibration must not run")):
            [(status, label, reason)] = selftest.check_speed_now(config)
        self.assertEqual((status, label), (selftest.WARN, "speed now"))
        self.assertIn("held by fixture", reason)
