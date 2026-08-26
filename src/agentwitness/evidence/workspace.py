"""Workspace state fingerprints used to reject stale verification evidence.

Inspired by the freshness rules used by Backcheck and truth: a green test run
only describes the tree that existed when the test ran. AgentWitness records a
content fingerprint with test evidence and compares it with the current tree at
verification time.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Iterable, Tuple

_RELEVANT_EXTENSIONS = {
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".rs", ".go", ".java", ".kt", ".kts", ".scala", ".c", ".cc",
    ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift", ".sh",
    ".ps1", ".psm1", ".toml", ".yaml", ".yml", ".json", ".xml",
    ".ini", ".cfg", ".lock",
}
_RELEVANT_NAMES = {"Dockerfile", "Makefile", "Justfile", "Taskfile.yml"}
_IGNORED_PARTS = {
    ".git", ".agentwitness", ".pytest_cache", "__pycache__", "node_modules",
    "dist", "build", ".venv", "venv", "target", ".next", ".turbo",
}


def _is_relevant(rel_path: str) -> bool:
    p = Path(rel_path)
    if any(part in _IGNORED_PARTS for part in p.parts):
        return False
    return p.name in _RELEVANT_NAMES or p.suffix.lower() in _RELEVANT_EXTENSIONS


def _git_root(cwd: str) -> Path | None:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return Path(res.stdout.strip())
    except Exception:
        pass
    return None


def _git_paths(root: Path) -> Iterable[str] | None:
    try:
        res = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=str(root),
            capture_output=True,
            check=False,
        )
        if res.returncode != 0:
            return None
        return [p.decode("utf-8", errors="surrogateescape") for p in res.stdout.split(b"\0") if p]
    except Exception:
        return None


def workspace_fingerprint(cwd: str) -> Tuple[str, int]:
    """Return a deterministic hash of relevant current workspace contents.

    The hash never stores source contents in the ledger; only the SHA-256 digest
    and file count are retained. Documentation-only edits intentionally do not
    invalidate test evidence, while code, tests, build/config and lock files do.
    """

    root = _git_root(cwd) or Path(cwd).resolve()
    paths = _git_paths(root)
    if paths is None:
        paths = []
        for base, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in _IGNORED_PARTS]
            for name in files:
                rel = str((Path(base) / name).relative_to(root)).replace("\\", "/")
                paths.append(rel)

    relevant = sorted({p.replace("\\", "/") for p in paths if _is_relevant(p)})
    digest = hashlib.sha256()
    count = 0

    for rel in relevant:
        path = root / rel
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        digest.update(rel.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
        digest.update(b"\0")
        count += 1

    return digest.hexdigest(), count
