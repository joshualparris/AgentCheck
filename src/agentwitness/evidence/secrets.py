"""Deterministic secret-pattern checks for git diffs.

The scanner intentionally reports only file names, line numbers, and pattern
names. Matched secret values are never returned or written to the ledger.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class SecretHit:
    path: str
    line: int
    pattern: str


# These are common credential formats, not copied secret values. Keep the list
# intentionally small and auditable; a dedicated scanner can be integrated later.
_SECRET_PATTERNS = [
    ("openai-style-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("anthropic-style-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("github-pat", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("aws-access-key-id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("stripe-live-key", re.compile(r"\bsk_live_[A-Za-z0-9]{20,}\b")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
]

_DEFAULT_SKIP = [
    "*.example",
    "*.example.*",
    "tests/fixtures/*",
    "test/fixtures/*",
    "node_modules/*",
    "dist/*",
]


def _run_git(cwd: str, args: List[str]) -> Optional[str]:
    try:
        res = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return None
        return res.stdout
    except Exception:
        return None


def _diff_text(cwd: str, commit_sha: Optional[str]) -> Optional[str]:
    if commit_sha:
        return _run_git(cwd, ["show", "--format=", "--unified=0", commit_sha])

    staged = _run_git(cwd, ["diff", "--cached", "--unified=0"])
    working = _run_git(cwd, ["diff", "--unified=0"])
    if staged is None and working is None:
        return None
    return (staged or "") + "\n" + (working or "")


def _skipped(path: str, globs: Iterable[str]) -> bool:
    normalized = path.replace("\\", "/")
    return any(fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(Path(normalized).name, pattern) for pattern in globs)


def scan_git_diff_for_secrets(
    cwd: str,
    commit_sha: Optional[str] = None,
    skip_paths: Optional[List[str]] = None,
) -> Optional[List[SecretHit]]:
    """Scan added git-diff lines for common credential formats.

    Returns None when git evidence cannot be read, [] for a readable clean diff,
    or SecretHit entries containing metadata only (never the matched value).
    """

    text = _diff_text(cwd, commit_sha)
    if text is None:
        return None

    skip = list(_DEFAULT_SKIP)
    if skip_paths:
        skip.extend(skip_paths)

    hits: List[SecretHit] = []
    current_path = ""
    new_line = 0

    for raw in text.splitlines():
        if raw.startswith("+++ b/"):
            current_path = raw[6:]
            continue
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)(?:,(\d+))?", raw)
            if match:
                new_line = int(match.group(1)) - 1
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            new_line += 1
            if not current_path or _skipped(current_path, skip):
                continue
            line = raw[1:]
            for name, pattern in _SECRET_PATTERNS:
                if pattern.search(line):
                    hits.append(SecretHit(path=current_path, line=new_line, pattern=name))
        elif not raw.startswith("-"):
            # Context lines increment the new-file line number.
            new_line += 1

    return hits
