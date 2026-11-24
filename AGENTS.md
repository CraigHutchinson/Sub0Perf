# Repository guidance

Sub0Perf is the performance tooling of the Sub0 family: `cmake/Sub0Perf.cmake`, `tools/perf/` (the `sub0perf` Python
package and `bench_check.py`), `tools/perf/bench_runner.hpp` and `vendor/nanobench.h`. Use generic examples in source,
tests, documentation, issues and pull requests; no product names, and never name a private repository (this one is public).

- Scope: statistics, verdicts, baselines, gates, hooks and profiler glue. Host mechanism (processes, locks, directories,
  topology) belongs in Sub0Platform; the maths belongs in Sub0Math.
- **Changes here affect every consumer** (every library that benchmarks, through CPM). Keep names, command lines, file
  formats and schemas stable; the names are `sub0perf_*` / `SUB0PERF_*`; the old `sub0math_*` / `SUB0MATH_*` ones are read as fallbacks for one release (docs/PERFORMANCE.md, "Names").
- Standard library only for the Python; tests use synthetic samples, records and temporary git repositories.
- Read [docs/PERFORMANCE.md](docs/PERFORMANCE.md) before changing the gate or its output.
