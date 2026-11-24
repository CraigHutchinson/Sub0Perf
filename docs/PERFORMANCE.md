# Performance tooling

Sub0Perf is the Sub0 family's performance tooling: `cmake/Sub0Perf.cmake` and `tools/perf/`. Every library that
benchmarks gets the same benchmark runner, budgets, gate and profiler targets:

```cmake
include("${Sub0Perf_SOURCE_DIR}/cmake/Sub0Perf.cmake")      # after CPMAddPackage(NAME Sub0Perf ...)
sub0math_target_perf_options(MyLibrary)                       # profile / vectorization / native options
sub0math_add_benchmark(MyLibrary_Bench bench_my_library.cpp)    # plus _json/_check/_baseline/_compare/_vtune_*/...
```

The function and variable names keep their `sub0math_` / `SUB0MATH_` prefix for now (the tooling moved out of Sub0Math
unchanged; renaming is a later change). Configuring writes the scripts' location to `<build>/sub0math_tooling_dir.txt`, so
shells and CI can run them without knowing where CPM put Sub0Perf. Benchmarks include `<bench_runner.hpp>` and accept
`--filter` (case-insensitive substring), `--json`, `--soak <seconds>` (loop under a profiler) and `--list`.

## Timing budgets (per host)

```bash
cmake --build --preset default --target MyLibrary_Bench_check      # interleaved rounds; fails on a regression
cmake --build --preset default --target MyLibrary_Bench_baseline   # record this host's baseline from them
```

**Implicit after every rebuild.** A benchmark executable relinks only when its code, or a header it
uses, has changed. When it does, a quick-level check runs straight after the build (3 rounds at the
same epochs as baselines, so absolute times compare like for like, within the quick time budget; see [Levels](#levels-time-budget-and-coverage)) and prints regressions and progressions. `SUB0MATH_PERF_ON_BUILD` controls this:

| Value | Effect |
|---|---|
| `REPORT` (default) | Report only |
| `ENFORCE` | A regression fails the build |
| `OFF` | No check (CI uses this; its own job runs the full rounds) |

**How a measurement is made robust** (`tools/perf/bench_check.py`, implemented in the `sub0perf` package, see [Tooling layout](#tooling-layout)):

| Threat | Countermeasure |
|---|---|
| Thermal and turbo drift during a run | **Interleaved rounds:** every benchmark once per round, each in its own process, in an order shuffled per round (seeded). Drift spreads over all benchmarks instead of biasing the last ones |
| Clock speed varying within and between runs | **Calibration:** a fixed dependent arithmetic chain (`--calibration`) is timed at the start and end of each round. Each sample is scaled by the clock interpolated at its position in the round. Baselines record calibration, so a slower session is corrected before judging. Measured here: the core runs about 3% slower at the end of a round than at its start |
| Environment changes the clock does not show (cache and memory contention, other load) | **Controls:** hand-written references do not use the library, so whatever moves them is the environment. After calibration, their median change is factored out, and a shift beyond half the tolerance is reported. Seen: a commit touching only Python and docs was blocked because every benchmark, the references included, ran 7–28% slower while the clock moved 4.5%. The controls showed +13.3%, and with that factored out nothing regressed, while an injected +30% on one library benchmark is still caught. Repositories without hand-written references get calibration only, and the report says so |
| Environment shifted too far to judge absolute times | When the controls move by more than the tolerance beyond the clock, absolute verdicts become **ENVIRONMENT** (inconclusive, never blocking). Pair ratios and instruction counts are relative to the same environment and still judge. Seen: a +41% shift while another process ran benchmark rounds |
| Core migration and preemption | Each measurement is pinned to one logical CPU (`--cpu`, default the last) at raised priority. Spreads fell from a 2.7% median and 17.6% worst to 1.1% and 7.6%, and calibration from 0.6% to 0.1% |
| Other load on the machine | **Load check:** CPU time used by other processes is sampled before each round. Above `--max-load` (20%) the run waits up to `--settle` seconds, then records the round as busy. The report states how many rounds ran busy |
| Two timing levels from process to process | **Bimodal detection:** a benchmark whose samples form two clusters (largest gap at least 2% of the median and four times the spread inside the clusters, at least two samples each, from five rounds) is checked level by level. A regression needs the *fast* level to be slower than the baseline by more than the threshold, an improvement the slow level faster; if only one level moved, the verdict is **NOISY** (marked `bimodal` in the report), which the gate retries with more rounds and never blocks on. Both levels moving is a real change and keeps its verdict. Pair ratios get the same treatment. See the 2026-10-20 finding for the evidence. Hardening (2026-10-21): a benchmark that is bimodal now or in the baseline is never used as an environment **control** (its level change would be "corrected" into every other benchmark); a baseline stores `modes` `[low, high]` for bimodal benchmarks and pairs, and a shift counts only if it clears the baseline's *slow* level (regression) or *fast* level (improvement), at the clock with and without the controls' correction; the report says `bimodal, both levels moved` when a bimodal row keeps REGRESSED/IMPROVED. The test needs 5 measured samples and 2 per side, so a confirmation or retry pass always gathers at least 10 measured samples (`stats.MODES_MIN_SAMPLES`) for what it re-measures, and the gate measures benchmarks the baseline knows to be bimodal that long from the start. **Cost of the rule:** a real regression smaller than the gap between the two levels can be hidden. With the box group's levels about 18% apart, a uniform slowdown of up to about 15% can read as one level moving. A bimodal benchmark is therefore weak evidence, and changes in its code should be judged by an explicit A/B or by its pair ratio, not by the gate alone |
| Noise mistaken for change | **Variance:** a robust spread (median absolute deviation) per benchmark across rounds. A change must exceed both the tolerance (10%) and 3x the noise. Spread above `--max-cv` (5%) is **NOISY**: the quick check adds rounds for those benchmarks (up to double) and then reports them as inconclusive, never as passed or failed |
| Clock-dependent time, and changes too small for timing noise | **Hardware counters, where the OS exposes them** (Linux perf_event on bare metal; not Windows, WSL2 or GitHub's hosted runners, which are virtual machines without the processor's counters). The report and checks use them per op: instructions are nearly deterministic, so they are judged at a 2% tolerance (`--instr-tolerance`) and catch added work that timing noise hides; cycles do not depend on clock speed; IPC and branch-miss rate are shown. Pairs add the instruction ratio against the hand-written reference. A counter regression blocks like a time regression, and `accept` logs counter changes too. Elsewhere the report says counters are unavailable |
| Host-dependent absolute times | **Pairs:** each hand-written reference's group is reported as a ratio taken from adjacent measurements in the same round. This is nearly independent of the host, so CI and new machines get it without a baseline |

**Verdicts, reported implicitly in every check:** REGRESSED, IMPROVED (a progression: record it with
`_baseline` and say why in the commit), ok, NOISY, new and missing, for benchmarks and for pair ratios
(pair tolerance 5%).

### Levels, time budget and coverage

The rigour added in October 2026 (at least 10 measured samples before a bimodal benchmark can block, kept
binaries, side-by-side reproduction, confirmation passes) made one pre-push gate of a whole
suite take more than 10 minutes, and that cost landed on every everyday push. So the gates have two levels:
**quick** for everyday work, **full** for milestones. Quick gives a baseline of coverage in a target time;
full is the complete method, unchanged.

| | `quick` (default) | `full` |
|---|---|---|
| Used by | pre-push gate, after-build check | milestone pushes, or on request |
| Benchmarks | 2 environment controls (hand-written references) always; whole groups (a pair group, or a standalone benchmark) rotate, stalest first, to fill the budget | all |
| Rounds | 3, the least that gives a median and a spread | the gate's default (3), plus extra rounds wherever the rules below ask for them |
| Time | a budget, **90 s** by default (a target: confirming a regression may overrun it) | none, unless one is given |
| Bimodal-known benchmarks | measured to 10 samples only when a verdict depends on it (a regression to confirm, an inconclusive result to retry) | measured to 10 samples from the start |
| Confirmation of a regression | always, even if it overruns the budget (the overrun is reported) | always |
| Inconclusive retry | only if it fits the remaining budget | always |
| Side-by-side reproduction against the kept binary | only for a regression against a local record, as in full | the same |
| Records and kept binaries | kept (a record of a quick run holds the benchmarks it measured) | kept |

Quick never weakens what a confirmed regression means: a regression against the committed baseline, or one
that reproduces side by side against the previous record, blocks at either level, and is confirmed with the
same extra rounds (at least 10 measured samples of what is re-measured). What quick gives up is **coverage
per push**: a benchmark that was not measured this push, or stayed inconclusive, cannot block it.

**Which level runs** (the first that applies, reported with its reason on the first line of the gate output):

1. `--level quick|full` on the command line;
2. the environment variable `SUB0MATH_PERF_LEVEL=quick|full`;
3. the pushed refs: a push that includes a **tag** whose name matches one of the full-ref patterns runs
   full. Defaults `v*` and `milestone/*` (so `v1.2.0`, `milestone/M2`); change them with the CMake list
   `SUB0MATH_PERF_FULL_REFS` or `bench_check.py install-hooks --full-refs "rel-*,v*"` (stored as `full_refs`
   in `.git/sub0perf/config.json`). Branch names and deletions never match;
4. otherwise quick.

**The budget** is `--budget SECONDS`, else `SUB0MATH_PERF_BUDGET`, else (quick only) the configured value,
else 90. CMake sets the configured value with `SUB0MATH_PERF_QUICK_BUDGET` (stored as `quick_budget`; the
after-build check gets it as `--budget`). `0` means no budget. Full has none unless one is given. It counts
measuring time: the build before it does not count.

**The planner** (`sub0perf/plan.py`) spends it like this:

- The unit of rotation is a **group**: a pair group (a library benchmark with its hand-written twin, measured
  back to back in the same rounds) or a standalone benchmark. A pair ratio is a self-contained relative check,
  so a pair group is valid whenever it is selected and need not run every push.
- Cost per sample comes from the timings of the last runs (`.git/sub0perf/coverage/<target>.json`: the
  median wall time of each benchmark's process, which includes process start-up, and of a round's two
  steady calibrations). With none yet, one calibration is timed too, and every benchmark without a cost is probed as below;
  a cold single sample under-estimates, so the first plan on a machine is optimistic and the next is accurate.
- **Always measured: 2 controls**, the cheapest hand-written references that the baseline does not know to be
  bimodal (the same exclusion the judge applies). Two is the least that lets one disagree with the other,
  and absolute verdicts need the environment correction they give. They run for 3 rounds, the least that
  gives a median and a spread.
- **Re-check first:** groups whose last result was a regression (confirmed or not) or inconclusive are
  stored (`recheck`) and go next, but together they may take at most half of the spendable budget. A group
  measured later without being flagged is cleared.
- 25% of the budget is kept for confirmation and retry passes. The rest is filled with whole groups,
  **stalest first**: never measured, then longest since last measured (counted in gate runs; a group's age is
  its stalest member's); ties are broken by a hash of the commit and the group, so the choice for a
  commit is repeatable and differs between commits. A group too expensive for the space left is skipped
  and stays stalest, and cheaper ones fill the rest.
- If the stalest group alone does not fit beside the controls but fits the whole budget, it is **measured
  alone** (otherwise cheaper groups would keep it waiting for ever) and the overrun is stated. A group that
  would cost more than the whole budget beside the controls is **not measured yet**: it is listed in the plan
  and left to the full level, since quick promises its time.
- **Benchmarks with no recorded cost** (new ones) are timed first, one sample each, before anything is
  planned: a sample is cut off after a tenth of the budget and all such probes together take at most a fifth
  of it, and their time counts against the budget. A benchmark that hits the cut-off is recorded as `slow` in
  the coverage file and, like one the allowance did not reach, is not planned at quick (it has no baseline, so
  it cannot regress; the full level measures it and clears the mark). On 2026-11-03 eight new whole-run
  benchmarks, never measured and costed at the median of the others, were all planned first, 3 rounds of
  minutes per sample each; the gate ran 58 minutes instead of 90 s.
- The gate prints what it will do and the coverage it gives, for example `plan: 14/30 benchmarks x 3
  rounds, estimated 66 s of a 90 s budget`, `controls, always: 2 hand-written reference(s) (...); groups this
  push: 6 of 22`, `coverage: measured 14/30 now; every group is covered within 4 push(es)`, `stalest after
  this push: <group> (never measured)`. The cycle length is a replay of the following pushes from the measured
  costs (without re-checks), so it is exact for steady costs.
- After the run it prints the measured time against the budget, and the overrun when there is one.
  `.git/sub0perf/log.jsonl` has the level, benchmarks measured and seconds of every gate.

A run that measured a subset judges against the same baseline: benchmarks it did not measure are not
`missing`, only the measured ones get a verdict.

**Milestone procedure.** Before declaring a milestone (a release, a design freeze, merging a long
branch), run the full level and read its output:

```bash
SUB0MATH_PERF_LEVEL=full git push          # or: git push origin v1.2.0 / milestone/M3 (a matching tag selects full)
python tools/perf/bench_check.py gate --level full      # by hand, without pushing
```

Baselines are (re)recorded only from **full-level, steady** runs: record them with the `_baseline` target
or `bench_check.py baseline` from a `run` of the whole suite, never from a quick record. The calibration
steadiness guard (refusal when the calibration varied by more than 1.25x) applies unchanged. A quick record
contains only the benchmarks it measured, so `accept` of a benchmark it did not measure fails by design:
measure it first (`run --filter ...`).

**Quality gates (tests) have the same two levels.** A long test suite is labelled `full` (ctest label); the
everyday run excludes it and milestones and CI run everything:

```cmake
include("${Sub0Perf_SOURCE_DIR}/cmake/Sub0Perf.cmake")
sub0math_add_test(MyLib_Tests COMMAND MyLib_Tests)                 # quick: runs every day
sub0math_add_test(MyLib_Soak FULL COMMAND MyLib_Soak --long)       # full: milestones and CI
sub0math_label_full_tests(MyLib_Other)                             # label a test that already exists
doctest_discover_tests(MyLib_Long ADD_LABELS 1 TEST_SUFFIX " [full]")  # discovery macros: use their own LABELS option
gtest_discover_tests(MyLib_Long PROPERTIES LABELS full)
```

```bash
ctest --preset quick     # or: ctest -C Release -LE full     everyday local runs
ctest --preset full      # or: ctest -C Release              milestones, and CI (always everything)
```

`CMakePresets.json` has `quick` and `full` test presets (inheriting `default`; `quick` has
`"filter": {"exclude": {"label": "full"}}`). CI keeps its existing presets, which run everything.

### Self-test of the gate

A gate that quietly does the wrong thing is worse than none (on 2026-11-03 one measured everything on a push with
nothing to push, and a quick run took 58 minutes against a 90 s budget). `bench_check.py selftest` proves the wiring in
seconds, without building or measuring anything:

```bash
python tools/perf/bench_check.py selftest --repo . [--target NAME] [--budget SECONDS]
```

It prints a table of PASS, WARN and FAIL rows and exits 1 on any FAIL. Consumers run it as the `selftest` of
`.ci/local.json` (see `docs/ci-strategy.md`, "Local gates must self-test").

| Check | Passes when |
|---|---|
| `hook pre-push`, `hook post-checkout` | The hook is in the directory git looks in (`core.hooksPath` honoured), is a sub0perf hook, calls an existing `bench_check.py` and an existing python, and is byte-identical to what `install-hooks` writes for this tooling. Other python or script paths with the same logic are a WARN; a changed hook is a FAIL (drift: re-run `install-hooks`). In a tracked hooks directory, or under `SUB0MATH_PERF_HOOK_MODE=chain`, the committed hook must either carry the one chaining line (and `.git/sub0perf/hooks/<hook>` must match) or run `bench_check.py gate --refs-from-stdin` itself, the shared `templates/pre-push` stanza (PASS; WARN without `--refs-from-stdin`, or while no tooling record exists yet; FAIL for a literal path that does not exist). Neither is a FAIL, with both wirings named, and the chaining line to add |
| `config`, `target <name>`, `baseline` | `.git/sub0perf/config.json` parses; the baseline exists and has benchmarks. A missing build dir or executable is a WARN ("not built yet") |
| `pin <name>`, `config full_refs/quick_budget` | Pin entries have file and var and repo or checkout, the file exists and its `set(VAR <sha>)` parses; settings have the right type |
| `gate: empty stdin`, `deletion only`, `docs-only range` | The real `gate_command` skips each, with synthetic refs |
| `gate: code range` | The gate plans a measuring run, and the quick plan's predicted seconds plus the probe allowance (a fifth of the budget while any benchmark has no recorded cost) fit the budget, from the repository's real coverage state |
| `coverage <name>` | Always reported: benchmarks with no recorded cost (unknown), probed too slow (full level only), groups deferred, pushes to cover every group, the stalest group. A WARN while any is unknown or slow |
| `gate power: ...` | With the power state faked (`SUB0PERF_FAKE_POWER`): battery and a battery saver defer, strict mode fails, `SUB0MATH_PERF_ON_BATTERY=1` and unknown power measure; each deferral names the override |
| `baseline power: ...` | Mains, old (no field) and unknown records may become a baseline; battery and override runs may not |
| `power now` | Always reported; a WARN on battery ("the gate would defer, measuring nothing") |
| `lock` | No stale `.git/sub0perf/lock` (a live one is a WARN) |

The decisions are the gate's own code, not a copy: `gate_command` has a **plan-only mode** (`args.plan_only`) that
takes every decision up to the point where it would take the lock and build, then stops, recording why in
`args.outcome` and the quick plan per target in `args.previews`. It does not run the pins' network check, write the
log, or care about a dirty tree or `SUB0MATH_PERF_SKIP`, and `args.changed_paths` replaces the git diff of the pushed
range (the selftest injects a docs-only list and a code list). The benchmark names come from the baseline and the
coverage state, since listing them would run the benchmark executable. `choose_benchmarks` and the preview share
`make_quick_plan`, so the plan is the one a real quick gate makes.

### Power state

Timing on battery is not a fair comparison with a baseline recorded on mains: CPU clocks, boost and the power plan all
differ, and the run burns battery for a verdict nobody can trust. `sub0perf/power.py` reads the state (`ac`, `battery` or
`unknown`, plus whether a battery saver or low-power mode is on): `GetSystemPowerStatus` on Windows (the active power
plan is reported too), `/sys/class/power_supply` on Linux (no battery means mains), `pmset` on macOS. `unknown` (a
desktop, a runner, a failed query) counts as mains but is reported as unknown. `bench_check.py power` prints the state and
the switches in effect (exit 3 on battery).

- **Deferral (default).** After the empty-push and documentation-only skips, and before building or measuring, a gate on
  battery (or in a saver) prints `on battery: performance not measured (deferred; ...)` with how to override, and exits 0.
  The baseline and the coverage state are not touched, so the stalest-first rotation resumes where it stopped. The pushed
  ranges go to `.git/sub0perf/deferred.json`; the next gate on mains lists them, and if it blocks it says the regression
  may come from any of them. They are cleared by a clean measurement on mains. Nothing maps a changed file to the
  benchmarks it affects, so deferred pushes do not reorder the rotation. `SUB0MATH_PERF_LEVEL=full` covers everything.
- **Strict.** `SUB0MATH_PERF_POWER_STRICT=1`, or `"strict_power": true` in `.git/sub0perf/config.json`, refuses the push
  instead (exit 1). Off by default.
- **Override.** `SUB0MATH_PERF_ON_BATTERY=1` measures anyway. The first line of the run and the last line of the summary say
  so, the record carries `"power": {"state": "battery", ...}` and `"power_override": true`, the report shows it, and such a
  record can never become a baseline. Set on mains it is reported as "set but ignored (on mains)", so a stale export is noticed.
- **Mid-run.** Power is checked before every round (including confirmation rounds). A switch to battery stops the run: the
  measurements are discarded (no verdicts, no record), the push is deferred like any other, and the range is marked
  "stopped mid-run".
- **Records.** Every samples record and baseline carries `power`. `baseline` and `accept` refuse a record measured on
  battery or in a saver; `--force-power` allows one made by hand, never one measured under the override. `unknown` is
  allowed and says so. A baseline without the field is mains. When the record's power state (battery, saver) differs from
  the baseline's, absolute verdicts become ENVIRONMENT (inconclusive); pair ratios and instruction counts still judge.
- **Tests only.** `SUB0PERF_FAKE_POWER=ac|battery|unknown|saver` replaces the query; outside tests the gate warns that the
  power state is being faked. The decision tests and `selftest` use it.
- **After-build check.** The `auto` run after a build defers on battery the same way (it is a measurement too).

#### Throttled machine on mains

Mains is not enough: a vendor power mode, a charging power cap or thermal limits can pin the CPU at its base clock with no
boost, and every timing then comes out a uniform factor slower (a laptop on mains, plan Balanced, ran 2.4x slow while the
power state read `ac`). The sub0perf environment controls would flag such a run ENVIRONMENT, but only after measuring
everything. `sub0perf/speed.py` catches it first:

- **The check.** Before any build, the gate times the benchmark executable's own `--calibration` kernel (a fixed dependent
  arithmetic chain, single thread, about 0.3 s) and divides it by the `calibration_ns` stored in the baseline, which the same
  kernel produced. It uses the executable already built (no build is needed), pinned like the measurements. A reading over the
  limit is repeated until two agree, because the first reading after idle runs at a cold clock (about 1.9x on the reference
  host, gone on the next run). It is skipped, with a line saying so, when there is no built executable or the baseline has no
  calibration (a first run on a host), and on battery (which defers anyway).
- **Sustained speed, not only burst.** A 0.3 s kernel runs inside the boost window. On a laptop in the Windows power mode
  "Best power efficiency" (overlay `961cc777-2547-4f9d-8174-7d86181b8a7a`) every core held boost for about 3 s of load and then fell
  to about 0.42x (P-cores) and 0.33x (E-cores): every rolling-cost test of a consumer library read 2.4x slower while the 0.3 s kernel read
  0.97x and the check passed. The check therefore also takes a **sustained** reading: `--calibration --soak <s>` runs the kernel
  continuously in one process for `warm_seconds` (default 4.5 s; `SUB0MATH_PERF_WARM_SECONDS` or `"warm_seconds"` in the config;
  0 = burst only) and reports the median of the last quarter. It must be one process (the slowdown does not carry into a new one;
  15 short readings back to back all read 1.00x, a single long process read 2.4x). The gate acts on the slower of the burst and
  sustained ratios. The sustained reading is compared with `calibration_sustained_ns` in the baseline, which `sub0perf run` records
  (4.5 s extra, not on battery or when throttled); a baseline without it is compared with this run's own burst reading (a machine
  that drops past the limit within seconds is throttled whatever the baseline says) and the note says so. An executable built
  before `--soak` returns at once; that is noticed, noted, and only the burst reading is used (rebuild to get the check). The
  sustained part is skipped when the burst is already over the limit, and on battery. **Cost:** 4.5 s plus a process start per push
  that has something to measure (after the empty-push and docs-only skips), about 5 % of the quick gate's 90 s budget.
- **Power mode.** On Windows the deferral names the power-mode overlay (`ActiveOverlayAcPowerScheme` / `ActiveOverlayDcPowerScheme`
  under `HKLM\SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes`, read only): `bench_check.py power` prints both
  ("power mode Best power efficiency (mains) / Best power efficiency (battery)"), records carry them as `power.mode`, and a throttled
  machine in "Best power efficiency" is told to set Balanced or Best performance. sub0perf never changes a setting.
- **Limit.** Slower than 1.4x is `throttled` (`SUB0MATH_PERF_THROTTLE_RATIO`, or `"throttle_ratio"` in
  `.git/sub0perf/config.json`). The default comes from the 32 local records of the reference host: the median calibration of a
  run stays within 0.97x..1.29x of the baseline's (the high end overlapped other load), while a machine pinned at base clock
  reads about 1.9x. Raise it for a host whose normal spread is wider; do not lower it below the spread of your own records.
- **Handling.** Exactly as battery: deferral (exit 0, the range goes to `deferred.json`), strict mode refuses, and
  `SUB0MATH_PERF_ON_BATTERY=1` measures anyway. The switch keeps its published name and covers both states. The message gives
  the ratio and the likely causes (vendor power mode, charging cap, thermal). An override run is flagged (`power.throttled`,
  `power_override`) and can never become a baseline; a throttled record that was not an override (a run made by hand) needs
  `--force-power`, like battery. A record whose throttled flag differs from the baseline's judges absolute verdicts as
  ENVIRONMENT.
- **Records.** `power.speed_ratio` holds the measured ratio in every gate and `auto` record (also when fine), so a drift in a
  host's normal ratio shows in the records. `bench_check.py power --exe BENCH --baseline FILE` prints the check (exit 3 when
  throttled); `selftest` shows the ratio now as the `speed now` row.
- **Limits of the check.** It is a single-thread kernel for a few seconds: a cap that bites only under sustained all-core load, or a
  throttle that builds up over minutes, is not seen before measuring. The existing clock-drift and control checks still
  catch those afterwards. The Windows `% Processor Performance` counter is not used: it averages all cores, so a single idle-ish
  probe cannot read it meaningfully. The ratio is only meaningful against a baseline recorded on the same host.
- **Tests only.** `SUB0PERF_FAKE_SPEED=<ratio>` replaces the burst measurement and `SUB0PERF_FAKE_SUSTAINED=<ratio>` the sustained
  one (alone: burst fine, sustained throttled); the gate warns when either is set. The unit tests and `selftest` use them, with fake
  calibration readers for the measurement itself.

### Pre-push gate and explicit acceptance

Configuring a repository that builds benchmarks installs two git hooks, unless on CI or
`SUB0MATH_PERF_GIT_HOOKS=OFF`. A hook that is not ours is never overwritten: it is renamed to
`<hook>.user` and the installed hook runs it first (with the same arguments and stdin; if it fails, so
does the push). Paths in the hooks are shell-quoted, and when python or the tooling directory is gone
a hook prints a message and does nothing instead of failing.

**A tracked hooks directory is never touched.** When `core.hooksPath` points inside the worktree (for example
`.githooks`), its files are committed and shared, so install-hooks does not rename or overwrite them, and does not add
files there. Two wirings are valid for the committed `pre-push`, and `selftest` accepts either:

1. **The hook runs the gate itself.** A hand-written hook that reads the pushed refs from stdin (a loop over `read`, as the shared
   `templates/pre-push` of the `.github` repository does to skip documentation-only pushes) and runs
   `bench_check.py gate --refs-from-stdin` with them: the template's commented perf stanza, which finds the tooling in
   `SUB0PERF_TOOLING_DIR` or the newest `<build>/sub0math_tooling_dir.txt` under `build*/` and `build/*/` (a preset's build
   directory is `build/<preset>`). This is the wiring for a hook that reads stdin, because stdin can be read once.
2. **The chain line.** For a committed hook that does not read stdin itself, or for an untracked `.git/hooks` under
   `SUB0MATH_PERF_HOOK_MODE=chain`. Our hooks are kept in `.git/sub0perf/hooks/<hook>` (never tracked) and install-hooks prints
   the one line to add to the committed hook, before anything reads stdin. Do not add it to a hook of the first kind: the
   chained copy reads all of stdin first, and the hook's own loop then sees no refs. install-hooks prints nothing for a
   committed `pre-push` that already runs the gate itself.

The chain line:

```sh
[ ! -f "$(git rev-parse --path-format=absolute --git-common-dir)/sub0perf/hooks/pre-push" ] || sh "$(git rev-parse --path-format=absolute --git-common-dir)/sub0perf/hooks/pre-push" "$@" || exit $?
```

It prints nothing once the line is there. `SUB0MATH_PERF_HOOK_MODE=chain` does the same for an ordinary `.git/hooks`: nothing is
written into git's hooks directory, and the line is printed. `install` (the default) keeps the rename-to-`.user` behaviour for
an untracked hooks directory. `selftest` checks the line and the chained copy (see below).

- **post-checkout** notes the commit. The first clean build afterwards keeps its measurement as that
  commit's record: `.git/sub0perf/records/<target>/<commit>.json`, local to the clone and never
  committed. So every commit measured on a clean tree has a record of where a branch started.
- **pre-push** builds each benchmark target, measures HEAD at the selected level (see [Levels](#levels-time-budget-and-coverage); 3 interleaved rounds, plus extra rounds
  for noisy benchmarks) and keeps that as HEAD's record. It then compares against:
  - the committed baseline;
  - the record of the upstream commit, or of the nearest earlier commit with one, which is like for
    like on this machine.

  Any regression against the baseline that persists blocks the push, with the exact command to accept it.

  **A difference from the local record blocks only if it reproduces.** The record was measured in an
  earlier session, and a difference from it was twice not the code (two benchmarks of a consumer library: REGRESSED against the record, identical
  times when the two builds were measured alternately). Likely causes, all properties of the *session*
  and none removable by scaling: the clock and power state, other load and thermal state at the time
  of the record (the calibration chain tracks the core clock but not cache and memory behaviour, which
  the dynamics benchmarks are bound by), a bimodal benchmark landing on a different level per process,
  and few rounds on either side. So each record keeps the benchmark executable that made it
  (`.git/sub0perf/bins/<target>/<commit>/`, newest 3 kept). A regression against the record is
  then confirmed by measuring that kept build and the new one alternately (order swapped each round, at
  least 10 rounds, the regressed groups only) and judging the new build against the *fresh* measurement
  of the old: only names that still regress block. Names that do not are reported as `not reproduced`
  (a WARNING, logged as `unreproduced_vs_record`). When the old build was not kept (records made before
  this existed, or pruned) or cannot run, nothing can be shown and the differences from the record only
  warn. The committed baseline is not affected: it is the reviewed reference, and a regression against it
  still blocks after the usual confirmation.

  **What is measured is what is pushed.** The hook reads the refs git passes on stdin. It refuses the
  push, saying why, when tracked files have uncommitted changes (the build would include them), or when
  the commit being pushed for any ref (deletions excepted) is not the checked-out HEAD. A push that
  only deletes refs is not measured, and neither is one whose every update against the remote changes only
  documentation (Markdown, `docs/`, licence files, provenance manifests under `upstream/`, CI configuration under `.github/` and `.ci/`): measuring then could only find noise, and a bimodal
  benchmark once blocked an AGENTS.md change. The skip is logged. A new branch, or a remote commit not
  present locally, is always measured. Otherwise the build is the pushed commit and the gate proceeds.
  Run by hand (`bench_check.py gate`, without `--refs-from-stdin`) it only warns about a dirty tree.

  **Inconclusive results retry, then warn.** If the result includes NOISY or ENVIRONMENT verdicts
  (against either comparison), the groups involved are measured once more with as many extra rounds
  as the first measurement had (so the rounds double). What is still inconclusive then does not block:
  the gate prints a WARNING naming each benchmark, and stores the list in the local record
  (`inconclusive`, with `inconclusive_retried`) and in `.git/sub0perf/log.jsonl`. Only REGRESSED blocks.
  A method mismatch (different epochs or pinned CPU, including unpinned against pinned) is reported
  as inconclusive but not retried, since more rounds cannot fix it.

  **One run at a time.** Measuring runs on a repository (`gate`, and `auto` with `--repo`, which the
  after-build check uses) take the lock `.git/sub0perf/lock` (pid, time, what), so concurrent runs
  cannot interleave and disturb each other's timing. A second run waits (`--lock-timeout`, default
  900 s) and then gives up. A lock whose process has gone, or older than six hours, is taken over.

  **Bypass.** `SUB0MATH_PERF_SKIP=<reason> git push` skips the gate; the reason is printed and logged
  as a `skip` event. (The gate's own build sets it internally so the after-build check does not run.)

  **Dependency pins.** A repository that pins a dependency by commit (`set(X_REVISION <sha>)` read by
  `CPMAddPackage(... GIT_TAG ${X_REVISION})`) must not push the pin before the dependency itself: CI
  then fails to fetch it ("unable to read tree"). Pins are declared at hook install, generically, as
  `install-hooks --pin file=cmake/Dependencies.cmake,var=X_REVISION,repo=owner/name[,checkout=../X][,name=X]`
  (repeatable; from CMake, the list `SUB0MATH_PERF_PINS`) and kept under `pins` in
  `.git/sub0perf/config.json`. When the pushed range changes the pin file (a new branch, whose range is
  unknown, counts), the sha is read from the pushed commit and looked up: `gh api repos/<owner>/<repo>/commits/<sha>`
  when `gh` is available (404/422 means absent), otherwise the sibling checkout's remote-tracking refs
  (`git branch -r --contains <sha>`, as fresh as its last fetch). Known absent: the push is refused with
  `push <name> first`. Unverifiable (offline, no `gh`, commit not in the checkout): a WARNING, the push
  goes on. A range that leaves the pin file alone, such as a documentation-only push, is not checked,
  which keeps the check free. It runs before the performance gate and is **not** bypassed by
  `SUB0MATH_PERF_SKIP`; `SUB0MATH_PINS_SKIP=<reason>` bypasses it, logged as `pins-skip`.

  Records (`.git/sub0perf/records/...`), samples files and baselines are written atomically (temp
  file, then replace), and records keep the shuffle `seed` of their rounds.

  **Confirmation pass.** Three rounds are not enough evidence to block on. Whatever is judged
  regressed on the first pass (a benchmark, a pair or a counter, against either comparison) is
  measured again, alone with its pair references, for `--confirm-rounds` more interleaved rounds
  (default 4, calibration as usual); both comparisons are then re-judged with all rounds. The gate
  prints `confirmed:` and `not confirmed:` lists and blocks only on the former. `auto` does the same.
  The pass is at least long enough to give every re-measured benchmark 10 measured samples (see bimodal
  detection), so with the default 3 initial rounds it adds 7, not 4, when a benchmark is short of them.

  **No controls.** A repository without a hand-written benchmark cannot factor out environment shifts.
  There, a change must also exceed 3x the suite's own spread of changes (median absolute deviation
  across all benchmarks in that comparison): it is judged against
  `max(tolerance, 3 x noise, 3 x suite spread)`, and the report says
  `No controls: suite spread X% used as an extra noise floor`. Repositories with controls keep the
  plain rule. The logic is covered by `python -m unittest discover -s tools/perf`.

### Tooling layout

`tools/perf/bench_check.py` is a thin shim with the command line below, so consumers (which find it
through `sub0math_tooling_dir.txt`) and installed git hooks (which call `bench_check.py gate
--refs-from-stdin` by path) are unaffected by the internals. The code is the `tools/perf/sub0perf`
package, lowest layer first:

| Module | Holds |
|---|---|
| `common` | Constants (`CALIBRATION`, `REFERENCE_MARK`), `group_of`, `read_json`, `atomic_write_text`, `tooling_script` |
| `platform_proc` | CPU pinning and priority, launching a measurement, machine CPU time counters, `pid_alive` |
| `load` | System load sampling, waiting for a quiet machine |
| `power`, `deferral` | The power state (`power_state`, the gate's policy and messages); pushes deferred on battery |
| `stats` | Robust CV, bimodal detection (`modes`, `rounds_needed`), calibration-scaled medians (`summarise`), `pair_ratios` |
| `baseline` | The two file formats: samples record (`make_record`, `write_samples`) and baseline (`baseline_data`, `baseline_tuple`, `write_baseline`) |
| `gitstate` | `git`, HEAD, clean tree, `.git/sub0perf` (records, log), pushed refs, documentation-only pushes |
| `runner` | One process per benchmark, interleaved calibrated rounds, `extend_rounds`, `measure_all`, `rerunner` |
| `judge` | Verdicts for benchmarks, pairs and counters, environment controls, method mismatch; `evaluate`, `verdict_hits` |
| `confirm` | Confirming regressions, retrying inconclusive results |
| `levels` | Which level (quick or full) and budget a run has: `--level`, `SUB0MATH_PERF_LEVEL`, pushed milestone tags |
| `plan` | The quick-level planner: pairs and controls always, rotation by staleness, coverage state, the time `Budget` |
| `reproduce` | Measuring an earlier record's kept build beside the new one to reproduce a difference from the record |
| `compare` | The `compare` command: interleaved A/B of two builds (two executables, or a kept build), at least 10 rounds |
| `metrics` | Deterministic metrics: judging a metrics file against `perf/metrics.json` (exact, max, xfail) and logged `accept --metric` |
| `output` | The output contract (`--format brief|json|md`, `--report`, `SUB0PERF_OUTPUT`) and holding back the chatter of long runs |
| `pins` | Dependency pins: parsing, reading the sha, checking it is on the dependency's remote |
| `report` | The markdown tables and job summary |
| `accept` | `baseline` and `accept` commands (the logged `accepted` list) |
| `lock`, `hooks`, `gate` | One run at a time; installing and chaining hooks; the pre-push gate (with a plan-only mode) |
| `selftest` | The `selftest` command: hook, config, gate decisions and lock checks that build and measure nothing |
| `cli` | Argument parsing and the commands |

Tests live in `sub0perf/tests/`, one file per area, and are found by `python -m unittest discover -s
tools/perf` (the CI `python-tests` job). Change behaviour in the module that owns it; shared logic
(for example, "names with a verdict among benchmarks, pairs and counters") exists once, in `judge`.

A regression is accepted only explicitly, and only in the baseline you push:

```bash
python tools/perf/bench_check.py accept --results .git/sub0perf/records/<target>/<commit>.json     --baseline perf/baselines/<host>.json --benchmark "<name>" --reason "why this is acceptable"
```

`accept` needs measured samples for every named benchmark in `--results`: a benchmark that is absent, or
has only filled-in copies of a median, is an error naming it (exit 2, baseline untouched) rather than a
silent no-change entry. Measure it first, for example `bench_check.py run --exe <bench> --filter "<name or
group>" --out samples.json`, then accept from that file.

`accept` and `baseline` also refuse a run whose calibration kernel varied by more than 1.25x across its
rounds (exit 2, baseline untouched), because the machine was not steady. In one run the calibration read
5,046 ns and 9,042 ns, and scaling by it moved every accepted median by 30–40%. Re-measure on a quiet machine.

This moves those benchmarks' baseline (and pair ratios) to the new measurement and appends an entry to
the baseline's `accepted` log: date, commit, reason, before and after. Commit the file with the change.
The gate then lets a regression through against the earlier record only if an acceptance for that
benchmark was added since that commit (read from the baseline committed at HEAD, not the working tree). `--all-changed` accepts every regressed or improved benchmark.
Re-recording a whole baseline also requires a reason once a baseline exists, and is logged the same
way: `bench_check.py baseline --reason "..."`, or
`SUB0MATH_PERF_REASON="..." cmake --build build --target <target>_baseline`. `git push --no-verify` bypasses the hook, as with
any git hook; the baseline log is the record that should explain why.

Baselines live in `perf/baselines/<host>.json`: median, spread and rounds per benchmark, calibration
time, and pair ratios. Timings from one machine say nothing about another, so each host has its own.
`<host>` is `SUB0MATH_PERF_HOST` (a CMake cache variable, default the lower-cased host name), and the `"host"` field of the
baseline and of the records carries that name, not the machine's own; the build targets pass it to the tooling as the
environment variable of the same name, which a shell can set too.
Baselines in the older format (a number per benchmark) are still read, judged against the suite's
median drift, and should be re-recorded. A library's CI should not time anything: it builds with
`-DSUB0MATH_BUILD_BENCHMARKS=OFF` (and `SUB0MATH_PERF_ON_BUILD=OFF`, `SUB0MATH_PERF_GIT_HOOKS=OFF`), because shared
runners are too noisy, and runs the tooling's own Python tests (`python -m unittest discover -s tools/perf`).
Timing is the local gate's job. What may run anywhere is the deterministic part: the `<target>_smoke` and
`<target>_metrics` ctest tests (label `smoke`), which never time ([Deterministic metrics](#deterministic-metrics)).

## Deterministic metrics

Some facts about a build do not depend on the machine: the size of a type, the number of iterations a solver
needs, the bytes a path allocates, a count of kernel calls. They need no calibration, no rounds and no noise
floor, so they are judged exactly, in milliseconds, and may run in every `ctest` and in CI.

```cpp
sub0bench::BenchRunner runner(argc, argv, "My library");
runner.metric("sizeof Vec3<double>", sizeof(Vec3<double>), "B");                          // exact (the default)
runner.metric("iterations to converge", iterations, "n", sub0bench::MetricKind::max);     // a ceiling
```

`runner.metric(name, value, unit, kind = exact|max)` registers a value (the last value of a name wins). Call it
before the runs, or inside a workload: the two modes below run each selected workload once. The runner gains
two flags that never time anything:

| Flag | Does |
|---|---|
| `--metrics-only` | Runs each selected workload once and writes `{"metrics":[{"name","value","unit","kind"}]}` to the `--json` file, or to stdout without one |
| `--smoke` | Runs each selected workload once; the exit status is the only output (0, or 1 when nothing matched) |

A committed spec, `perf/metrics.json`, says what each metric must be:

```json
{"schema": "sub0perf-metrics-spec-1",
 "metrics": {"sizeof Vec3<double>": {"kind": "exact", "expected": 24, "unit": "B"},
             "iterations to converge": {"kind": "max", "limit": 40},
             "known gap": {"kind": "exact", "expected": 1, "xfail": "why it is expected to fail today"}},
 "accepted": []}
```

```bash
python tools/perf/bench_check.py metrics --exe <bench> --spec perf/metrics.json           # runs --metrics-only itself
python tools/perf/bench_check.py metrics --results metrics.json --spec perf/metrics.json
```

`exact` must equal `expected` (an optional absolute `tolerance`), `max` must not exceed `limit`. `xfail` takes a
reason for a metric that is expected to fail: while it fails (XFAIL) it does not block, and when it starts to pass
(XPASS) it does, so the marker gets removed. A spec metric the executable does not report is MISSING (blocks); a reported
metric the spec lacks is NEW (listed, does not block). Exit 1 on FAIL, XPASS or MISSING; exit 2 on unreadable input.

Moving a metric is explicit and logged, like a baseline: `accept --metric NAME... --reason "why"` (with
`--spec`, and `--results` or `--exe`) sets the metric's `expected` (or `limit`) to the measured value, clears the `xfail` of a metric that is named,
and appends date, commit, reason, before and after to the spec's `accepted` list. `--all-changed` takes the failing and the
new metrics and **never an xfail one** (it would move the value and leave the marker; the skipped names are printed): an
`xfail` is cleared only by naming its metric. The spec is edited in place with the smallest change: its layout, indentation
and key order stay, only the accepted value, a removed `xfail`, a new metric and the appended log entry differ, so the diff
to review is the change. (If a layout cannot be followed the file is rewritten in full, and that is said.) Commit the spec
with the change.

```cmake
sub0math_add_benchmark(MyLibrary_Bench bench_my_library.cpp METRICS perf/metrics.json SMOKE_TEST)
```

`SMOKE_TEST` registers ctest test `<target>_smoke`; `METRICS <spec>` (relative to the project root) registers
`<target>_metrics` and the target `<target>_metrics_accept` (reason in `SUB0MATH_PERF_REASON`; failing and new metrics, never an
xfail one, unless `-DSUB0MATH_ACCEPT_METRIC="name;name"` names the metrics, which also clears their `xfail`). Both tests carry the
label `smoke` and never time, so `ctest` and CI may run them: a layout or iteration-count regression is then a red test,
and a benchmark that crashes is caught without a timing machine. The sample benchmark in `examples/` shows it.

## Output contract

`check`, `auto`, `gate`, `compare` and `metrics` print in one of three formats, chosen with `--format brief|json|md`.
The environment variable `SUB0PERF_OUTPUT=brief` makes brief the default (for hooks and agents); `--format` wins.
Without either, the format is `md`, as before.

- **brief**: ONE verdict line, then one line per row changed beyond noise (REGRESSED or IMPROVED; inconclusive and
  unchanged rows are only counted):

  ```text
  perf: FAIL 1 regressed, 0 improved, 14 ok, 2 inconclusive; report build/perf/X.report.md
  REGRESSED index/cold 1e5: +14.2% (noise 2.1%, tol 10%)
  ```

  `perf compare:` and `perf metrics:` prefix their own commands (`perf metrics: FAIL 1 failed, 0 xfail, 12 ok` then
  `FAILED size: 32 B != expected 24`). With `--report-only` the status still says FAIL, but the exit status is 0.
- **json**: exactly one object on stdout, schema `sub0perf-outcome-1`, mirroring `sub0perf-workload-outcome-1`:
  `{"schema", "command", "status": "PASS|FAIL", "exit", "counts": {"regressed","improved","ok","inconclusive"},
  "changed": [{"name","kind":"benchmark|pair|counter","verdict","change","noise","tolerance"}], "report", "next_action"}`.
  `next_action` is the command to run next (an `accept ...` line after a regression). `metrics` has its own
  `counts` (`failed`, `xpass`, `missing`, `xfail`, `new`, `ok`). A run that reached no verdict (a skipped gate, a deferral)
  prints `status: "NO_VERDICT"` with the last lines in `log`.
- **md**: the full markdown tables on stdout.

**The outcome file.** `--out-json PATH` (or the environment variable `SUB0PERF_OUTCOME_JSON`; the flag wins) on `check`, `auto`,
`gate`, `compare` and `metrics` also writes the `sub0perf-outcome-1` object to `PATH`, whatever `--format` is, so a runner
reads a file instead of parsing stdout: `local_ci.py`'s `"perf_outcome": "{builddir}/perf-outcome.json"` needs only
`bench_check.py gate --level full --out-json {builddir}/perf-outcome.json`. The directory is created and the file replaced
atomically. A run that reached no verdict (a deferral, a refusal, unusable input, a crash) writes `status: "NO_VERDICT"`
with the command's own `exit`; `exit` is always the process's exit status. A command that never reaches an outcome writes
no file unless asked.

The full markdown tables go to the report file, `--report <path>` (brief and json always write one; the default sits
beside the samples file, `X.report.md`, or beside the executable, `<exe>.compare.md`; the gate uses
`<build>/perf/<target>.report.md`). `GITHUB_STEP_SUMMARY` still gets the tables. In brief and json the chatter of a long
run (`auto`, `gate`, `compare`: rounds, plans, notes) is held back in `<report>.log` (`.git/sub0perf/last-run.log` for the gate
without `--report`), and only the lines that matter (refusals, blocked pushes, warnings, failures) follow the verdict.

## Improve loop

The loop an agent or a person follows to make something faster, in commands and in few tokens read: [PERF_LOOP.md](PERF_LOOP.md)
(a skill file for agents is `tools/perf/skill/SKILL.md`). In short: `_runs` then `_check --format brief`, change, `_compare`
against the kept previous build (`bench_check.py compare`, at least 10 interleaved rounds), keep or reject, iterate up to the
three-pass rule, then `accept --reason` or `_baseline --reason` from a full steady run, and commit the baseline with the change.

`compare` measures two builds alternately (which goes first flips every round) in this session, so a difference is the
code and not the machine's state; it is the logic of the gate's reproduction step, exposed as a command:

```bash
python tools/perf/bench_check.py compare --exe <new bench> --against <old bench> [--filter TEXT] [--rounds 10]
python tools/perf/bench_check.py compare --exe <new bench> --kept [SHA] --repo .   # newest kept build that differs from --exe, or SHA's
cmake --build build --target <target>_compare                                      # the same, against the kept build
```

A build is kept (`.git/sub0perf/bins/<target>/<commit>/`, the newest three) whenever a clean tree is measured by the
after-build check (`--record`) or the gate. `--filter` keeps whole groups, so a pair keeps its hand-written reference.
REGRESSED means the new build is slower than the old one. CMake: `SUB0MATH_COMPARE_AGAINST=<exe>` and
`SUB0MATH_COMPARE_FILTER=<text>` replace the kept build and add a filter.

## Profiling

Build with the `profile` preset (optimised, debug info, frame pointers), then:

```bash
cmake --preset profile -DSUB0MATH_PROFILE_FILTER="rotate" -DSUB0MATH_PROFILE_SECONDS=5
cmake --build --preset profile --target MyLibrary_Bench_vtune_hotspots    # where time goes
cmake --build --preset profile --target MyLibrary_Bench_vtune_uarch       # why: front/back-end, ports, memory
cmake --build --preset profile --target MyLibrary_Bench_advisor_roofline  # vectorization and roofline
cmake --build --preset profile --target MyLibrary_Bench_perf_record       # Linux perf
```

Each target soaks the selected benchmark under the profiler, writes results to
`build-profile/profiles/<analysis>-<filter>-<time>/`, prints the summary and says how to open the GUI.
`tools/perf/profile.py` does the same without CMake.

- **VTune** reads GCC/Clang DWARF and MSVC PDB symbols on Windows and Linux.
- **Advisor** on Windows gives full loop and FLOP data for MSVC or Intel compiler builds; GCC builds
  still show loops and time.
- **ITT** task markers for VTune timelines belong with a library's runtime code.

## Whole-process workload evidence

A calibrated kernel gate cannot certify a complete invocation's memory budget or that two runs used
identical data/configuration. The shared adapter adds these checks without introducing a parallel,
weaker timing judge:

```sh
python tools/perf/bench_check.py workload measure --spec experiment.json --repo . --out build/evidence-001.json &&
python tools/perf/bench_check.py workload check --results build/evidence-001.json --max-rss-mib 512
```

The spec uses argument arrays (no shell), explicit executable paths, nonempty caller-defined identity,
and named input files. Paths are relative to the spec file, except absolute paths. Example shape
(replace the executable and input paths with real ones):

```json
{
  "command": ["./build/Benchmark", "--filter", "kernel"],
  "correctness": ["./build/IndependentVerifier"],
  "identity": {"workload": "fixed fixture", "workers": 1, "precision": "f32"},
  "inputs": {"data": "fixtures/data.bin", "config": "fixtures/config.json"},
  "cache": "uncontrolled",
  "environment": {"OMP_NUM_THREADS": "1"}
}
```

`measure` requires at least three samples. The declared independent correctness command must exit zero
before any measured invocation. Its adequacy remains the caller's responsibility; a successful run
or listing alone is not a numerical oracle. Each child is bounded by `--timeout` (120 seconds by
default); timeout/interruption kills its process group and reaps the child. Current RSS collection
requires Linux `wait4`; other platforms return a structured refusal, not an estimate. RSS is each
invocation's child high-water mark in MiB, independent of earlier verifier/warmup processes. It is not
simultaneous aggregate process-tree memory, device memory, or a working-set planner.

The adapter reuses sub0perf's shared repository lock for input hashing, verification, priming and
measurement, plus its load/power/provenance helpers. It refuses busy rounds above 5% (rather than
silently measuring them), simulated/untrusted/changing power, failed commands, timeouts, and input,
spec or executable changes. Unknown power remains labelled. Locking one checkout cannot prevent
foreign workloads; the load check is not exclusive CPU ownership. `cache: warm` performs one priming
invocation; `uncontrolled` makes no residency guarantee. Verified cold capture is unsupported.

Records (`sub0perf-workload-1`) retain input/executable SHA256, verifier identity/arguments, explicit
threading environment, allowed CPU affinity, host/power, source commit/dirty flag, all per-child RSS
and elapsed samples, output digests, and method/spec identities. Hash large inputs completely before
and after the run; this I/O happens outside timed samples, inside the shared lock, and can be expensive.
Scripts and verifier data must be declared as inputs; interpreter hashing alone cannot identify them.
Caller-declared environment values are stored, so do not put secrets there. Other inherited environment
is not exhaustive; declare consequential settings. A dirty source tree is diagnostic, not a reviewed
baseline or proof of which source built an executable. New evidence paths are published atomically
without overwriting existing paths, including concurrent publishers. No-clobber publication requires
hard-link support on the output filesystem; it refuses if unavailable.

`check --baseline earlier.json` first refuses incompatible identity/input hashes, verifier identity or
arguments, cache/warmup method, adapter/timer method, threading environment, affinity, host or power.
The measured binary may differ between arms; a stable independent verifier must not. Supply the same
argument/input paths across arms. The worst measured RSS is checked against the explicitly chosen
absolute budget; there is no automatic budget acceptance.

**Agent/automation contract:** `bench_check.py workload` emits exactly one JSON outcome on stdout
for an action, including missing/invalid arguments and runtime refusals; helper diagnostics go to
stderr. `--help` remains human-readable. Outcomes have schema `sub0perf-workload-outcome-1`, a `status`,
`elapsed_verdict: unjudged`, and `next_action`. Status/exit codes are:

| Status | Exit | Meaning |
|---|---|---|
| `recorded` | 0 | Complete evidence published; check its memory budget next |
| `within-budget` | 0 | RSS budget satisfied; optional compatibility check matched |
| `over-budget` | 1 | Observed RSS exceeded the explicit budget |
| `refused` | 2 | Arguments, evidence, oracle, environment or execution invalid; includes `error` |

Neither exit zero nor RSS success is a time-performance pass. Elapsed covers the whole process,
including startup, with a 10 ms polling bound. It is diagnostic and uncalibrated. Existing
`run`/`auto`/`gate` timing judgments, confirmation, reproduction and explicit acceptance are unchanged.
Keep domain-specific quality, denominator, phase, cache and memory-pressure policies in the consumer;
this shared layer supplies evidence/provenance and absolute RSS checking only.
