"""Correctness before timing, end to end: a real benchmark executable whose one row fails its --smoke run is reported and never timed."""

import contextlib
import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from .. import output, runner

ROOT = Path(__file__).resolve().parents[4]
PERF = ROOT / "tools" / "perf"
VENDOR = ROOT / "vendor"
COMPILER = shutil.which("g++") or shutil.which("clang++") or shutil.which("c++")

SOURCE = r'''
#define ANKERL_NANOBENCH_IMPLEMENT
#include <bench_runner.hpp>
#include <stdexcept>

int main(int argc, char** argv)
{
    sub0bench::BenchRunner runner(argc, argv, "gate");
    int n = 0;
    runner.run("fine", [&] { ++n; ankerl::nanobench::doNotOptimizeAway(n); });
    runner.run("broken", [&] {
        if (n == 0) throw std::runtime_error("the answer is wrong");  // --smoke runs this workload once, with n still 0
        ankerl::nanobench::doNotOptimizeAway(n);
    });
    return runner.finish();
}
'''


@unittest.skipUnless(COMPILER and (VENDOR / "nanobench.h").is_file(), "needs a C++ compiler and vendor/nanobench.h")
class SmokeGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        source = Path(cls.tmp.name) / "gate.cpp"
        source.write_text(SOURCE, encoding="utf-8")
        cls.exe = Path(cls.tmp.name) / "gate.exe"
        built = subprocess.run([COMPILER, "-std=c++20", "-O0", f"-I{PERF}", f"-I{VENDOR}", str(source), "-o", str(cls.exe)],
                               capture_output=True, text=True)
        if built.returncode != 0:
            raise RuntimeError(built.stderr[-2000:])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        runner.set_process_cap(None)
        self.addCleanup(runner.set_process_cap, None)

    def test_a_row_that_fails_its_smoke_run_is_dropped_and_reported(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            passed = runner.smoke_check(str(self.exe), ["fine", "broken"])
        self.assertEqual(passed, ["fine"])
        self.assertEqual(list(runner.SMOKE_FAILED), ["broken"])
        self.assertIn("SMOKE FAILED broken", err.getvalue())
        counts = output.counts_of([], [], {"counter_rows": []})
        self.assertEqual(counts["smoke_failed"], 1)
        self.assertEqual(output.status_of(counts), "FAIL")

    def test_a_row_that_passes_is_checked_once_per_command(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(runner.smoke_check(str(self.exe), ["fine"]), ["fine"])
            self.assertEqual(runner.smoke_check("/does/not/exist", ["fine"]), ["fine"])  # remembered: the executable is not run again
        self.assertEqual(runner.SMOKE_FAILED, {})


if __name__ == "__main__":
    unittest.main()
