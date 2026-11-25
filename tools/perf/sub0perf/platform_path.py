"""Finding Sub0Platform's Python package (`sub0platform`) without installing it.

Sub0Perf keeps the tooling standard-library only, so nothing is pip-installed: the configure step fetches Sub0Platform at a pinned tag
(CPM, download only) and records its `python/` directory, and this module puts that directory on `sys.path`. Where it looks, first hit wins:

  1. `sub0platform` is already importable (an installed or vendored copy: nothing to add)
  2. SUB0PERF_PLATFORM_DIR (the `python/` directory itself): CI and tests
  3. `platform_python` in the repository's `.git/sub0perf/config.json` (written by install-hooks, so a git hook finds it)
  4. `build*/sub0perf_platform_dir.txt` and `build/*/sub0perf_platform_dir.txt` under the working tree, newest first (written by configure)
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ENV_VAR = "SUB0PERF_PLATFORM_DIR"
RECORD = "sub0perf_platform_dir.txt"
PACKAGE = "sub0platform"


def _valid(directory):
    return bool(directory) and (Path(directory) / PACKAGE / "__init__.py").is_file()


def _git_dir(repo):
    out = subprocess.run(["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True, text=True)
    return Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None


def _top(repo):
    out = subprocess.run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else Path(repo)


def candidates(repo=None, environ=None):
    """The `python/` directories to try, first choice first."""
    environ = os.environ if environ is None else environ
    repo = _top(repo or ".")  # the working tree's top, so running from a subdirectory (tools/perf) still finds build*/
    found = [environ[ENV_VAR].strip()] if environ.get(ENV_VAR, "").strip() else []
    git_dir = _git_dir(repo)
    config = git_dir / "sub0perf" / "config.json" if git_dir else None
    if config and config.is_file():
        try:
            recorded = json.loads(config.read_text(encoding="utf-8")).get("platform_python")
            if recorded:
                found.append(recorded)
        except (OSError, ValueError):
            pass
    records = {p for pattern in (f"build*/{RECORD}", f"build/*/{RECORD}") for p in repo.glob(pattern)}
    for record in sorted(records, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            found.append(record.read_text(encoding="utf-8").strip())
        except OSError:
            continue
    return found


def ensure(repo=None, environ=None):
    """Makes `import sub0platform` work, or raises ImportError saying how to fix it. Returns the directory added, or None."""
    if importlib.util.find_spec(PACKAGE) is not None:
        return None
    tried = candidates(repo, environ)
    for directory in tried:
        if _valid(directory):
            sys.path.insert(0, str(directory))
            return str(directory)
    raise ImportError(f"sub0perf: the sub0platform package was not found (tried {', '.join(tried) or 'nothing recorded'}). Configure the build "
                      f"(it fetches Sub0Platform and records {RECORD}), or set {ENV_VAR} to Sub0Platform's python/ directory")


def loaded_dir():
    """The `python/` directory of the sub0platform this process imported (what an installing command can record), or None."""
    module = sys.modules.get(PACKAGE)
    where = getattr(module, "__file__", None)
    return str(Path(where).resolve().parent.parent) if where else None
