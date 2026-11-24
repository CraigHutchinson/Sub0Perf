# Sub0Perf Project Rules

Read [AGENTS.md](AGENTS.md) first.

## Build & Test

```bash
python -m unittest discover -s tools/perf
cmake --preset default && cmake --build --preset default && ctest --preset default
python tools/perf/bench_check.py selftest --repo .
```

Tests run in local CI (`local_ci.py --level quick` from the `.github` repository's `tools/ci`).

## Commit Rules

- A change to a `sub0perf_*` function, a `SUB0PERF_*` variable, a command line, a JSON schema or `bench_runner.hpp` says
  which consumers it affects.
- Tests pass locally before committing. Public repository: generic names only, run `private_names.py`.

## Branch Strategy

`main` is the integration branch. Use focused topic branches and pull requests.
