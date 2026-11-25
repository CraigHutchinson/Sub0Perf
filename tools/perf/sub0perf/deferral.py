"""Pushes held for measurement in `.git/sub0perf/deferred.json`.

The baseline and the coverage state are never touched by a deferral, so the stalest-first rotation resumes where it
stopped; this list only says which commits went unmeasured, so a regression found later is attributed to the right range.
"""

import json
import time

from . import machine
from .common import atomic_write_text, read_json
from .gitstate import git

KEEP = 50  # entries kept, newest last


def path(perf):
    return perf / "deferred.json" if perf else None


def load(perf):
    p = path(perf)
    try:
        found = read_json(p) if p and p.is_file() else []
    except (OSError, ValueError):
        found = []
    return found if isinstance(found, list) else []


def covered(repo, perf, head):
    """The deferred commits reachable from this gate's build."""
    return [entry for entry in load(perf) if git(repo, "merge-base", "--is-ancestor", entry["head"], head) is not None]


def _write_lock(perf):
    # Per-journal lock: a refused machine lease can defer while another gate owns it.
    held = machine.platform_lease().acquire("exclusive", "sub0perf", "update deferred ranges",
                                            lockFile=perf / "deferred.guard", timeout=5)
    if held is None:
        raise TimeoutError(f"the deferred journal at {path(perf)} is busy")
    return held


def add(perf, head, refs, reason, partial=False):
    """Records a push that was not measured: its head, ranges (remote..local per pushed ref) and why. `partial` = stopped mid-run."""
    if not perf:
        return
    ranges = [f"{r[2]}: {r[3][:9]}..{r[1][:9]}" for r in refs if set(r[1]) != {"0"}]
    pushed = [{"ref": ref, "from": old, "to": new} for _, new, ref, old in refs if set(new) != {"0"}]
    entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "head": head, "ranges": ranges, "refs": pushed,
             "reason": reason, "partial": partial}
    with _write_lock(perf):
        atomic_write_text(path(perf), json.dumps((load(perf) + [entry])[-KEEP:], indent=1) + "\n")


def clear(perf, measured=None):
    p = path(perf)
    if not p or measured == []:
        return
    with _write_lock(perf):
        pending = [entry for entry in load(perf) if measured is not None and entry not in measured]
        if pending:
            atomic_write_text(p, json.dumps(pending, indent=1) + "\n")
        else:
            p.unlink(missing_ok=True)


def describe(entries):
    """Lines for the next run on mains: which pushes went unmeasured."""
    if not entries:
        return []
    lines = [f"sub0perf: {len(entries)} earlier push(es) were not measured; this run measures against the "
             f"unchanged baseline, so a regression may come from any of them:"]
    for e in entries:
        lines.append(f"  - {e['time']} {e['head'][:9]} ({e['reason']}{', stopped mid-run' if e.get('partial') else ''})"
                     + (f": {'; '.join(e['ranges'])}" if e.get("ranges") else ""))
    return lines
