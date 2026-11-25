# CPU topology and parallel benchmark rows

The review covers ADR 0005, Sub0Platform at 2823cf3, and Sub0Perf at af59534. The first maintainer-facing slice shows which allowed logical CPUs share a physical core and where the operating system reports different classes. It gives the scheduler a way to identify separate cores before measuring whether rows interfere.

## Decisions

| Finding | Decision | Owner |
| --- | --- | --- |
| T1 (high). A ranked logical CPU list can contain two siblings from the same core. | Expose physical sibling groups clipped to the caller's affinity mask. Preserve unknown topology and class information so a caller can decline parallel work. | Sub0Platform |
| T2 (high). Windows affinity bits are group relative. The existing launcher starts the child before setting its mask and ignores the API result. | Limit the initial probe to one Windows processor group. Verify the requested effective affinity before benchmark execution in a later launcher change. | Sub0Platform |
| T3 (medium). Comparison records include the logical CPU and absolute comparisons depend on a matching CPU. | Receive topology through a read-only command. A scheduler will need an explicit CPU per launch and a measured per-host profile. | Sub0Perf |

Windows class evidence comes from [PROCESSOR_RELATIONSHIP](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-processor_relationship). Windows mask scope follows the [processor groups contract](https://learn.microsoft.com/en-us/windows/win32/procthread/processor-groups). Linux sibling groups come from [CPU topology in sysfs](https://docs.kernel.org/admin-guide/cputopology.html). CPU frequency is unsuitable as a fallback classification across operating systems.

## Order

1. Probe topology in Platform and verify sparse masks, SMT, incomplete records and Windows processor-group limits. Receive the probe in the Sub0Perf CLI with structured output and no timing.
2. Verify child affinity from the first benchmark instruction onward. Keep one candidate per physical core and retain serial execution when affinity or class information is insufficient.
3. Calibrate each eligible row in isolation and alongside pinned copies on a quiet host. Admit measured widths under the existing tolerance and spread rules. Keep baseline recording serial and cross-check admitted widths against serial measurements.

## Progress

Platform's [topology probe](https://github.com/CraigHutchinson/Sub0Platform/pull/5) passed its Windows and Linux CI matrix.
The Sub0Perf CLI passed a live probe on Windows and Ubuntu WSL. Parallel workers and row calibration are pending.
