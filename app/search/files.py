"""Read-only Mac file search backed by Spotlight (mdfind).

Only argv lists are passed to the runner (never a shell), the query is reduced
to letters, digits and single spaces so no mdfind syntax or leading dash gets
through, and results are limited to real files inside the configured roots
that are not hidden, secret or dependency folders.
"""

from __future__ import annotations

import subprocess
import unicodedata
from collections.abc import Callable, Sequence
from pathlib import Path

DEFAULT_ROOTS = ("~/Documents", "~/Desktop", "~/Downloads")
MAX_QUERY_CHARS = 80
MAX_SNIPPET_CHARS = 160
MAX_SNIPPET_BYTES = 1_000_000
TEXT_EXTENSIONS = frozenset(
    {".txt", ".md", ".markdown", ".rst", ".csv", ".json", ".yaml", ".yml",
     ".log", ".py", ".js", ".html", ".tex"}
)
EXCLUDED_DIR_NAMES = frozenset({"node_modules", "Library", "certs"})
_EXCLUDED_DIR_LOWER = frozenset(name.lower() for name in EXCLUDED_DIR_NAMES)
EXCLUDED_SUFFIXES = (".pem", ".key", ".p12")

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def sanitize_query(query: str) -> str:
    """Keep only letters, digits and single spaces; cap the length."""
    normalized = unicodedata.normalize("NFC", query)
    kept = "".join(ch for ch in normalized if ch == " " or ch.isalnum())
    return " ".join(kept.split())[:MAX_QUERY_CHARS].strip()


def _is_excluded(parts: Sequence[str]) -> bool:
    for part in parts:
        # Covers hidden entries, including every ".env*" file name.
        if part.startswith("."):
            return True
        if part.lower() in _EXCLUDED_DIR_LOWER:
            return True
    return parts[-1].lower().endswith(EXCLUDED_SUFFIXES)


def _is_allowed_file(path: Path, root: Path) -> bool:
    """Both `path` and `root` must already be resolved."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    if not rel.parts or _is_excluded(rel.parts):
        return False
    return path.is_file()


class FileSearch:
    """Find files by name or content through Spotlight, read-only."""

    def __init__(
        self,
        roots: Sequence[str | Path] | None = None,
        runner: Runner = subprocess.run,
        max_results: int = 5,
        timeout: float = 5.0,
        mdfind: str = "/usr/bin/mdfind",
    ) -> None:
        self._roots: tuple[str | Path, ...] = tuple(roots) if roots is not None else DEFAULT_ROOTS
        self._runner = runner
        self._max_results = max_results
        self._timeout = timeout
        self._mdfind = mdfind

    def _resolved_roots(self) -> list[Path]:
        resolved: list[Path] = []
        for raw in self._roots:
            root = Path(raw).expanduser().resolve()
            if root.is_dir():
                resolved.append(root)
        return resolved

    def search(self, query: str) -> list[dict]:
        cleaned = sanitize_query(query)
        if not cleaned or self._max_results <= 0:
            return []

        results: list[dict] = []
        seen: set[str] = set()
        for root in self._resolved_roots():
            argv = [self._mdfind, "-onlyin", str(root), cleaned]
            try:
                completed = self._runner(
                    argv,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                    check=False,
                )
            except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError):
                continue
            if completed.returncode != 0:
                continue

            for line in (completed.stdout or "").splitlines():
                if not line:
                    continue
                candidate = Path(line)
                if not candidate.is_absolute():
                    candidate = root / candidate
                try:
                    resolved = candidate.resolve()
                except (OSError, RuntimeError):
                    continue
                key = str(resolved)
                if key in seen or not _is_allowed_file(resolved, root):
                    continue
                seen.add(key)
                results.append({"path": key, "name": resolved.name})
                if len(results) >= self._max_results:
                    return results
        return results

    def _containing_root(self, path: Path) -> Path | None:
        for root in self._resolved_roots():
            try:
                path.relative_to(root)
            except ValueError:
                continue
            return root
        return None

    def snippet(self, path: str, query: str) -> str | None:
        """Return the first line matching any query word, or None."""
        try:
            words = [_fold(word) for word in sanitize_query(query).split() if _fold(word)]
            if not words:
                return None
            candidate = Path(path).expanduser().resolve()
            if candidate.suffix.lower() not in TEXT_EXTENSIONS:
                return None
            root = self._containing_root(candidate)
            if root is None or not _is_allowed_file(candidate, root):
                return None
            if candidate.stat().st_size > MAX_SNIPPET_BYTES:
                return None
            text = candidate.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                if "\x00" in line:
                    continue
                lowered = _fold(line)
                if any(word in lowered for word in words):
                    return line.strip()[:MAX_SNIPPET_CHARS]
            return None
        except Exception:  # noqa: BLE001 - snippets are best-effort, never raise
            return None
