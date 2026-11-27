"""ADR 0005 wait policy and blocked outcomes for timed commands."""

from dataclasses import asdict
import json
import sys

from . import output

INTERACTIVE_WAIT = 15 * 60
PUSH_WAIT = 120
NEXT_ACTION = "Rerun after the machine lease is released."
LEASE_STATUS_SCHEMA = "sub0perf-lease-status-1"


class Busy(Exception):
    def __init__(self, owners, wait):
        self.owners = owners
        self.wait = wait
        super().__init__(owner_text(owners))

    def blocked(self, deferred=False):
        return {"reason": "machine-lease", "holders": [asdict(owner) for owner in self.owners],
                "wait_seconds": self.wait, "deferred": deferred}


class Unavailable(Exception):
    """The Platform lease could not be loaded, opened or recorded."""


def platform_lease():
    # platform_proc resolves Sub0Platform before this is called. A cached older
    # package can still run correctness-only commands.
    try:
        from sub0platform import lease
    except ImportError as error:
        raise Unavailable("the Sub0Platform machine lease is unavailable. Reconfigure with the current Platform pin "
                          "or set SUB0PERF_PLATFORM_DIR to a checkout with sub0platform.lease.") from error
    return lease


def owner_text(owners):
    return " | ".join(owner.describe() for owner in owners) if owners else (
        "the machine lease is held. Wait for the holder to finish or stop it to release the lease.")


def take(what, *, no_wait=False, pre_push=False):
    lease = platform_lease()
    wait = 0 if no_wait else PUSH_WAIT if pre_push else INTERACTIVE_WAIT
    previous = None

    def waiting(owners):
        nonlocal previous
        if owners != previous:
            print(f"sub0perf: blocked: {owner_text(owners)} Waiting up to {wait} seconds.", file=sys.stderr, flush=True)
            previous = owners

    try:
        held = lease.acquire("exclusive", "sub0perf", what, timeout=wait, onWait=waiting)
        if held is not None:
            return held
        owners = lease.readOwners() or previous or []
    except OSError as error:
        raise Unavailable(f"cannot use the machine lease ({error})") from error
    raise Busy(owners, wait)


def status_command(args):
    """Show the Platform owner records without requesting or changing the lease."""
    try:
        owners = platform_lease().readOwners()
    except (Unavailable, OSError) as error:
        return report_unavailable(error)

    if output.resolve_format(args) == "json":
        print(json.dumps({"schema": LEASE_STATUS_SCHEMA, "advisory": True,
                          "reported_owners": [asdict(owner) for owner in owners]}))
    elif owners:
        print("sub0perf: machine lease owner records (advisory):")
        for owner in owners:
            print(f"  {owner.describe()}")
    else:
        print("sub0perf: no machine lease owners reported. Availability is determined when a lease is requested.")
    return 0


def report_blocked(args, error, *, deferred=False):
    code = 0 if deferred else 1
    status = "DEFERRED" if deferred else "BLOCKED"
    action = ("Rerun the gate when the machine is free and the checkout includes the deferred range." if deferred else NEXT_ACTION)
    data = output.outcome(args.command, status, code, None, [], None, action, blocked=error.blocked(deferred))
    output.record_outcome(data)
    with output.speaking():
        if output.resolve_format(args) == "json":
            print(json.dumps(data))
        else:
            print(f"sub0perf: {status.lower()}: {error} {action}")
    return code


def report_unavailable(error):
    print(f"sub0perf: error: {error}", file=sys.stderr)
    return 1
