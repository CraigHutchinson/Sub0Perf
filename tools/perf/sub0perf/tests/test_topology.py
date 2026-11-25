import contextlib
import io
import json
import sys
import unittest
from unittest.mock import patch

from sub0perf import cli
from sub0platform.topology import PhysicalCore


class TopologyCommandTests(unittest.TestCase):
    def report(self, cores, *arguments):
        stream = io.StringIO()
        with patch.object(sys, "argv", ["bench_check.py", "topology", *arguments]), \
                patch("sub0platform.topology.readTopology", return_value=cores), \
                patch.object(cli.machine, "take", side_effect=AssertionError("topology never takes a timing lease")), \
                contextlib.redirect_stdout(stream):
            self.assertEqual(cli.main(), 0)
        return stream.getvalue()

    def test_json_preserves_siblings_and_unknown_class(self):
        result = json.loads(self.report((PhysicalCore((2, 8), 1), PhysicalCore((16,), None)), "--format", "json"))
        self.assertEqual(result, {"available": True, "cores": [
            {"logical_cpus": [2, 8], "performance_class": 1},
            {"logical_cpus": [16], "performance_class": None},
        ]})

    def test_unavailable_topology_is_reported(self):
        self.assertEqual(json.loads(self.report(None, "--format", "json")), {"available": False, "cores": []})

    def test_text_displays_siblings_as_one_core(self):
        self.assertIn("logical CPUs 4, 12 share one physical core",
                      self.report((PhysicalCore((4, 12), None),), "--format", "md"))
