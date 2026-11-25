"""Sub0Perf.cmake finds its own Sub0Platform copy, whatever the consumer did with Sub0Platform_SOURCE_DIR."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CMAKE = shutil.which("cmake")


@unittest.skipUnless(CMAKE, "needs cmake")
class PlatformCopyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        text = ("cmake_minimum_required(VERSION 3.25)\nproject(t CXX)\n"
                f'include("{(ROOT / "cmake" / "get_cpm.cmake").as_posix()}")\n'
                'set(Sub0Platform_SOURCE_DIR "/consumer/own/cpp")\n'  # a consumer's own copy (SOURCE_SUBDIR cpp), another pin
                f'CPMAddPackage(NAME Sub0Perf SOURCE_DIR "{ROOT.as_posix()}" DOWNLOAD_ONLY YES)\n'
                'include("${Sub0Perf_SOURCE_DIR}/cmake/Sub0Perf.cmake")\n'
                'message(STATUS "PY=${SUB0PERF_PLATFORM_PYTHON}")\nmessage(STATUS "OWN=${Sub0Platform_SOURCE_DIR}")\n')
        (self.dir / "CMakeLists.txt").write_text(text, encoding="utf-8")

    def platform(self, launch):
        root = self.dir / "platform"
        (root / "python" / "sub0platform").mkdir(parents=True)
        (root / "python" / "sub0platform" / "proc.py").write_text("def launch(cmd):\n    pass\n" if launch else "def alive(p):\n    pass\n", encoding="utf-8")
        return root

    def configure(self, override):
        env = dict(os.environ, CPM_Sub0Platform_SOURCE=Path(override).as_posix())
        return subprocess.run([CMAKE, "-S", str(self.dir), "-B", str(self.dir / "b")], capture_output=True, text=True, env=env, timeout=300)

    def test_the_override_is_used_and_the_consumer_variable_is_left_alone(self):
        root = self.platform(True)
        done = self.configure(root)
        if done.returncode != 0 and "get_cpm" in done.stderr + done.stdout:
            self.skipTest("CPM could not be fetched")
        self.assertEqual(done.returncode, 0, done.stderr[-1500:])
        self.assertIn(f"PY={(root / 'python').as_posix()}", done.stdout)
        self.assertIn("OWN=/consumer/own/cpp", done.stdout)

    def test_a_platform_without_launch_stops_the_configure(self):
        done = self.configure(self.platform(False))
        if "get_cpm" in done.stderr + done.stdout:
            self.skipTest("CPM could not be fetched")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("has no launch()", done.stderr)


if __name__ == "__main__":
    unittest.main()
