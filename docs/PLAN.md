# Machine-wide scheduling plan

[ADR 0005](https://github.com/CraigHutchinson/.github/blob/main/docs/decisions/0005-machine-scheduling.md) was accepted on 2026-11-25. [Issue 3](https://github.com/CraigHutchinson/Sub0Perf/issues/3) tracks the rollout. The [Sub0Math extraction plan](https://github.com/CraigHutchinson/Sub0Math/blob/main/docs/plans/sub0perf-extraction.md) holds the migration history.

## Iteration 3

| Step | Delivery | Depends on |
| --- | --- | --- |
| 3.5 | [Sub0Platform lease](https://github.com/CraigHutchinson/Sub0Platform/issues/2). Add the C++ per-user state directory, shared file locking, Python and C++ lease APIs, and shared owner-record conformance vectors. | ADR 0005 |
| 3.6 | [Sub0Perf lease adoption](https://github.com/CraigHutchinson/Sub0Perf/issues/7). Receive the Platform lease in the timing entry points, then release `v0.4.0` and update consumer pins. | 3.5 |
| 3.7 | [Host topology](https://github.com/CraigHutchinson/Sub0Perf/issues/4), then [parallel benchmark rows](https://github.com/CraigHutchinson/Sub0Perf/issues/8) within one exclusive holder. | 3.6 |
| 3.8 | [Expose the common Sub0Perf scheduling workflow](https://github.com/CraigHutchinson/Sub0Perf/issues/25), then receive it in [Squad](https://github.com/CraigHutchinson/Sub0Squad/issues/8), [LlmEngine](https://github.com/CraigHutchinson/Sub0LlmEngine/issues/8), and [Canvas](https://github.com/CraigHutchinson/Sub0Canvas/issues/17). | 3.6 |
| 3.9 | Move `wasm_gate.py` and `upstream_provenance.py` to the family CI tools when either script is next touched. | A change to either script |

A maintainer running a gate should see the holder, its work, PID, start time, mode and the action that would unblock the run. Sub0Platform provides the common per-user lock and owner records. Sub0Perf owns the wait and deferral policy and takes its repository lock inside the machine lease. Smoke and metrics run without the lease. The first receiving slice pairs an exclusive Sub0Perf gate with a shared holder, exercises the blocked outcome, verifies deferral and strict refusal, and measures the deferred range after release.

### Sub0Perf lease policy

- Use the exclusive lease for the pre-push gate and for timed `compare`, `auto`, CMake and workload runs. Interactive commands announce the holder and wait up to 15 minutes. `--no-wait` fails immediately.
- The pre-push gate waits up to 120 seconds, then records the range in `.git/sub0perf/deferred.json` and lets the push proceed. The next gate measures that range. `SUB0PERF_LEASE_STRICT=1` refuses the push on timeout.
- Add a `blocked` object to `sub0perf-outcome-1` and print the human-readable holder message. Verify both the busy path and recovery after the holder exits.

### Scheduling interface and adoption

Start with observable leases and shared request policy in Sub0Perf. Use a synthetic serving holder and an exclusive
timing requester to prove refusal, owner reporting and recovery. Stage each consumer in its own issue.

Evaluate a persistent local endpoint for status, requests and bounded waiting. Preserve the Sub0Platform OS lease through
workload teardown and coordinator failure. A resource-specific reservation registry needs a follow-up decision under
[ADR 0005](https://github.com/CraigHutchinson/.github/blob/main/docs/decisions/0005-machine-scheduling.md).
One engine receiving case is a benchmark-owned backend started and stopped under the benchmark's exclusive lease.

### Release and consumer pins

`v0.4.0` also carries the stale-baseline diagnostic and the real-executable smoke-failure check from [PR 20](https://github.com/CraigHutchinson/Sub0Perf/pull/20), plus the standard-library metrics guard from [PR 21](https://github.com/CraigHutchinson/Sub0Perf/pull/21). Get explicit owner approval before tagging. Consumers pin the tagged commit SHA. Name the affected consumers in commit messages.

Update Sub0Canvas first. Re-run metrics `accept` on the recording toolchain to write the standard-library identifier into its spec. Check that the same library evaluates the spec and a different library reports a skip. Per-toolchain metric values remain deferred until a CI leg uses another standard library.

### Parallel benchmark rows

See the [topology review](reviews/2026-11-25-cpu-topology.md) for the affinity contract and the order of delivery.

1. Run smoke and deterministic metrics before timing. Report failed rows and exclude them from timing. This shipped in [PR 17](https://github.com/CraigHutchinson/Sub0Perf/pull/17).
2. Default to serial. The benchmark author opts each row in and sets an executable-wide ceiling via `sub0perf_add_benchmark(PARALLEL ...)` when the feature is implemented. Keep rows that use threads, large shared state, GPU, files or network serial.
3. Use Platform topology to separate performance and efficiency cores and keep SMT siblings apart. Calibrate each eligible row alone and alongside pinned copies. Accept the largest width whose median shift stays below one third of the gate tolerance and whose spread does not widen. Key the host profile by host, power state and toolchain. Fall back to serial on a key mismatch.
4. Pin concurrent processes to separate cores inside one exclusive holder. Cross-check against serial on first use and periodically afterwards. On a mismatch, switch to serial and report why.
5. Record all baselines serially. Compare parallel runs against those baselines using the calibrated shift.

The move of power and clock readers remains tracked in [Sub0Perf issue 4](https://github.com/CraigHutchinson/Sub0Perf/issues/4) and [Sub0Platform issue 1](https://github.com/CraigHutchinson/Sub0Platform/issues/1). Receive Platform's Python host module before moving the readers and removing the duplicate family CI power helper.

## Delivery checks

Use one topic PR per item and repository. Run the family private-name check before publishing. Keep shared checkouts on their active branches and run one pre-push timing gate at a time until the lease is deployed. If unchanged code is blocked, investigate gate behavior and host controls before re-recording a baseline.
