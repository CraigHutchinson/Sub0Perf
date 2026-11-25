# Sub0Perf

Performance tooling for the Sub0 family of C++ libraries: a benchmark runner, interleaved and calibrated timing rounds,
per-host baselines, a pre-push regression gate, deterministic metrics, an A/B compare loop and profiler targets.
Python (standard library only) and CMake; the runner is one C++ header on top of the vendored
[nanobench](https://github.com/martinus/nanobench).

It was extracted from Sub0Math, and its CMake functions and variables are `sub0perf_*` / `SUB0PERF_*`. The old
`sub0math_*` / `SUB0MATH_*` names still work for one release (docs/PERFORMANCE.md, "Names").

## Use

```cmake
CPMAddPackage(NAME Sub0Perf GITHUB_REPOSITORY CraigHutchinson/Sub0Perf GIT_TAG <commit-sha>)
include("${Sub0Perf_SOURCE_DIR}/cmake/Sub0Perf.cmake")
sub0perf_add_benchmark(MyLibrary_Bench bench_my_library.cpp METRICS perf/metrics.json SMOKE_TEST)
```

Releases are git tags (`v0.2.0`: the `sub0perf_*` / `SUB0PERF_*` names, processes from Sub0Platform, docs-only branch detection, bounded runs, correctness before timing). Consumers pin the tag's commit SHA. The old `sub0math_*` / `SUB0MATH_*` names still work in 0.2.x and go in `v0.3.0`. A local Sub0Platform checkout replaces the one Sub0Perf fetches: set `CPM_Sub0Platform_SOURCE`.

See [examples/bench_sample.cpp](examples/bench_sample.cpp) and [docs/PERFORMANCE.md](docs/PERFORMANCE.md) (timing budgets,
the gate, deterministic metrics, output contract, profiling) and [docs/PERF_LOOP.md](docs/PERF_LOOP.md) (the improve loop).

## Build and test this repository

```bash
python -m unittest discover -s tools/perf       # the tooling's own tests
cmake --preset default                           # configure the sample benchmark
cmake --build --preset default
ctest --preset default                           # sample smoke and metrics tests (no timing)
python tools/perf/bench_check.py selftest --repo .
```

Timing is never measured in CI: shared runners are too noisy. The gate runs locally, in each consumer's pre-push hook.
This repository dogfoods it on the sample benchmark: configuring installs the pre-push hook (not on CI) and
`perf/baselines/<host>.json` is the sample's baseline for the recording host, so `selftest` has something to check.

## Licence

MIT, see [LICENSE.md](LICENSE.md). `vendor/nanobench.h` is MIT-licensed by its author.
