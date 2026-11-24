"""The SUB0PERF_* environment variable names and their SUB0MATH_* predecessors.

The tooling reads the old names everywhere inside; `apply_aliases` makes either spelling work by setting the other from it when
only one is given, and the new one wins when both are. Environment variables stay quiet (no deprecation message), as the plan says.
Called once at the start of every command. Drop this module, and the old names in the code, when the fallbacks end.
"""

import os

# (new name, old name) for every variable the Python tooling reads.
PAIRS = (
    ("SUB0PERF_HOST", "SUB0MATH_PERF_HOST"),
    ("SUB0PERF_SKIP", "SUB0MATH_PERF_SKIP"),
    ("SUB0PERF_REASON", "SUB0MATH_PERF_REASON"),
    ("SUB0PERF_PINS_SKIP", "SUB0MATH_PINS_SKIP"),
    ("SUB0PERF_HOOK_MODE", "SUB0MATH_PERF_HOOK_MODE"),
    ("SUB0PERF_LEVEL", "SUB0MATH_PERF_LEVEL"),
    ("SUB0PERF_BUDGET", "SUB0MATH_PERF_BUDGET"),
    ("SUB0PERF_ON_BATTERY", "SUB0MATH_PERF_ON_BATTERY"),
    ("SUB0PERF_POWER_STRICT", "SUB0MATH_PERF_POWER_STRICT"),
    ("SUB0PERF_THROTTLE_RATIO", "SUB0MATH_PERF_THROTTLE_RATIO"),
    ("SUB0PERF_WARM_SECONDS", "SUB0MATH_PERF_WARM_SECONDS"),
)


def apply_aliases(environ=None):
    """Makes the new and old spelling of each variable agree in `environ` (default os.environ); the new one wins."""
    environ = os.environ if environ is None else environ
    for new, old in PAIRS:
        if new in environ:
            environ[old] = environ[new]
        elif old in environ:
            environ[new] = environ[old]
    return environ
