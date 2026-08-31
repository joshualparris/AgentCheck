"""Conservative classification of whether a pytest invocation covered a broad suite."""

from __future__ import annotations

from typing import Iterable, List, Tuple

_SCOPE_FLAGS_WITH_VALUE = {"-k", "-m"}
_SCOPE_FLAGS = {
    "--lf",
    "--last-failed",
    "--ff",
    "--failed-first",
    "--nf",
    "--new-first",
    "--sw",
    "--stepwise",
}


def classify_pytest_scope(argv: Iterable[str]) -> Tuple[bool, List[str]]:
    """Return (narrowed, reasons) for a pytest argv list.

    This intentionally errs toward refusing a broad "all tests pass" claim when
    the invocation obviously selected a subset. It does not attempt to infer the
    semantic completeness of the test suite itself.
    """

    args = list(argv)
    
    # Strip everything up to and including 'pytest' if invoked via python -m pytest
    # or just strip the executable path.
    start_idx = 1
    for idx, a in enumerate(args):
        base = a.lower().replace("\\", "/").split("/")[-1]
        if base in {"pytest", "pytest.exe"}:
            start_idx = idx + 1
            break
            
    pytest_args = args[start_idx:]
    reasons: List[str] = []
    i = 0
    while i < len(pytest_args):
        arg = pytest_args[i]
        low = arg.lower()

        if low in _SCOPE_FLAGS_WITH_VALUE:
            value = pytest_args[i + 1] if i + 1 < len(pytest_args) else ""
            reasons.append(f"{arg} {value}".strip())
            i += 2
            continue
        if (low.startswith("-k") and low != "-k") or (low.startswith("-m") and low != "-m"):
            reasons.append(arg)
        elif low in _SCOPE_FLAGS:
            reasons.append(arg)
        elif "::" in arg:
            reasons.append(f"node id {arg}")
        elif low.endswith(".py") and ("test" in low or "/tests/" in low.replace("\\", "/")):
            reasons.append(f"specific test file {arg}")

        i += 1

    return bool(reasons), reasons
