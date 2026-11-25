"""Tests for runner: steady calibration readings at the edges of a round."""

import contextlib
import io
import subprocess
import unittest
from unittest import mock

from .. import output, runner


class SteadyCalibrationTest(unittest.TestCase):
    def test_discards_cold_readings_until_two_agree(self):
        readings = iter([9030.0, 6100.0, 4910.0, 4890.0, 4880.0])
        self.assertEqual(runner.steady_calibration(lambda: next(readings)), 4890.0)

    def test_gives_up_after_the_attempt_limit(self):
        readings = iter([1000.0 * (i + 1) for i in range(20)])
        self.assertEqual(runner.steady_calibration(lambda: next(readings)), 1000.0 * runner.CALIBRATION_ATTEMPTS)


def passing_smoke(exe, names, cap_of=None):
    return list(names)


class SmokeBeforeTimingTest(unittest.TestCase):
    """A row whose --smoke run fails is reported, never timed, and blocks like a regression."""

    def setUp(self):
        self.addCleanup(runner.set_process_cap, None)
        runner.set_process_cap(None)

    def fake_run(self, failing):
        calls = []

        def run(cmd, **kwargs):
            calls.append(cmd)
            name = cmd[cmd.index("--exact") + 1]
            return subprocess.CompletedProcess(cmd, 1 if name in failing else 0, "", "check failed: expected 4, got 5" if name in failing else "")
        return run, calls

    def test_a_failing_row_is_not_timed_and_the_others_are(self):
        run, calls = self.fake_run({"bad"})
        timed = []

        def fake_measure_full(exe, args, scratch, timeout=None):
            timed.append(args[1])
            return {args[1]: (100.0, {})}
        err = io.StringIO()
        with mock.patch.object(runner.subprocess, "run", side_effect=run), mock.patch.object(runner, "measure_full", side_effect=fake_measure_full),                 mock.patch.object(runner, "measure", return_value={runner.CALIBRATION: 1000.0}),                 mock.patch.object(runner, "wait_for_quiet", return_value=(0.0, 0.0, True)), contextlib.redirect_stderr(err):
            samples, *_ = runner.run_rounds("exe", ["good", "bad"], 2, 0, 0.2, 0.0, 1)
        self.assertEqual(samples, {"good": [100.0, 100.0]})
        self.assertNotIn("bad", timed)
        self.assertEqual(runner.SMOKE_FAILED, {"bad": "check failed: expected 4, got 5"})
        self.assertIn("SMOKE FAILED bad", err.getvalue())
        self.assertEqual(sum(1 for c in calls if "good" in c), 1)  # the smoke run happens once per command, not once per round

    def test_the_outcome_lists_it_and_counts_it_as_blocking(self):
        runner.SMOKE_FAILED["bad"] = "check failed"
        args = type("A", (), {"tolerance": 0.1, "pair_tolerance": 0.05, "instr_tolerance": 0.02})
        rows = output.changed_rows([], [], {"counter_rows": []}, args)
        self.assertEqual([(r["name"], r["verdict"]) for r in rows], [("bad", "SMOKE_FAILED")])
        self.assertIn("SMOKE_FAILED bad: check failed", output.brief_line(rows[0]))
        self.assertEqual(output.counts_of([], [], {"counter_rows": []})["smoke_failed"], 1)
        self.assertEqual(output.status_of({"regressed": 0, "smoke_failed": 1}), "FAIL")

    def test_a_smoke_run_past_its_cap_fails_the_row(self):
        def run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
        with mock.patch.object(runner.subprocess, "run", side_effect=run), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(runner.smoke_check("exe", ["slow"], lambda n: 4.0), [])
        self.assertIn("past 4 s", runner.SMOKE_FAILED["slow"])


class ProcessCapTest(unittest.TestCase):
    """A benchmark process that outlives its cap is killed and reported TIMEOUT; the run goes on without it."""

    def setUp(self):
        self.addCleanup(runner.set_process_cap, None)

    def run_rounds(self, rounds=2):
        def fake_measure_full(exe, args, scratch, timeout=None):
            name = args[1]
            if name == "slow" and timeout is not None:
                raise subprocess.TimeoutExpired([exe], timeout)
            return {name: (100.0, {})}

        def fake_measure(exe, args, scratch, timeout=None):
            return {runner.CALIBRATION: 1000.0}
        err = io.StringIO()
        with mock.patch.object(runner, "smoke_check", side_effect=passing_smoke), mock.patch.object(runner, "measure_full", side_effect=fake_measure_full), mock.patch.object(runner, "measure", side_effect=fake_measure),                 mock.patch.object(runner, "wait_for_quiet", return_value=(0.0, 0.0, True)), contextlib.redirect_stderr(err):
            result = runner.run_rounds("exe", ["fast", "slow"], rounds, 0, 0.2, 0.0, 1)
        return result, err.getvalue()

    def test_a_row_that_hits_its_cap_is_dropped_and_reported(self):
        runner.set_process_cap(lambda name: 5.0)
        (samples, meta, positions, counters), err = self.run_rounds()
        self.assertEqual(samples, {"fast": [100.0, 100.0]})
        self.assertEqual(runner.TIMED_OUT, {"slow": 5.0})
        self.assertIn("TIMEOUT slow", err)
        self.assertEqual(len(meta), 2)

    def test_the_timed_out_row_is_not_tried_again_in_the_next_round(self):
        calls = []
        runner.set_process_cap(lambda name: calls.append(name) or 5.0)
        self.run_rounds(rounds=3)
        self.assertEqual(calls.count("slow"), 1)

    def test_timeouts_are_listed_in_the_outcome_and_never_count_as_regressions(self):
        runner.set_process_cap(lambda name: 5.0)
        self.run_rounds(rounds=1)
        args = type("A", (), {"tolerance": 0.1, "pair_tolerance": 0.05, "instr_tolerance": 0.02})
        rows = output.changed_rows([], [], {"counter_rows": []}, args)
        self.assertEqual([(r["name"], r["verdict"]) for r in rows], [("slow", "TIMEOUT")])
        self.assertIn("--filter", rows[0]["next_action"])
        self.assertIn("TIMEOUT slow", output.brief_line(rows[0]))

    def test_no_cap_means_no_limit(self):
        runner.set_process_cap(None)
        self.assertIsNone(runner.process_cap_for(0))
        self.assertEqual(runner.process_cap_for(300.0), 30.0)
        self.assertEqual(runner.process_cap_for(300.0, 20.0), 60.0)

    def test_progress_lines_go_to_stderr_with_round_count_and_eta(self):
        runner.progress.begin(4)
        (_, _, _, _), err = self.run_rounds(rounds=2)
        self.assertIn("round 1/4", err)
        self.assertIn("ETA", err)
