"""Tests for the read-only Spotlight file search. mdfind is never really called."""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.search.files import (
    MAX_QUERY_CHARS,
    MAX_SNIPPET_BYTES,
    FileSearch,
    sanitize_query,
)

MDFIND = "/usr/bin/mdfind"


class FakeMdfind:
    """Fake runner: returns the configured stdout per -onlyin root."""

    def __init__(
        self,
        lines_by_root: dict[str, list[str]] | None = None,
        returncode: int = 0,
        errors_by_root: dict[str, BaseException] | None = None,
    ) -> None:
        self.lines_by_root = lines_by_root or {}
        self.returncode = returncode
        self.errors_by_root = errors_by_root or {}
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        root = argv[argv.index("-onlyin") + 1]
        if root in self.errors_by_root:
            raise self.errors_by_root[root]
        lines = self.lines_by_root.get(root, [])
        stdout = "".join(f"{line}\n" for line in lines)
        return subprocess.CompletedProcess(argv, self.returncode, stdout=stdout, stderr="")


def _make(root: Path, rel: str, content: str = "x") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# --- sanitize_query -------------------------------------------------------

def test_sanitize_query_drops_dashes_and_mdfind_syntax() -> None:
    assert sanitize_query("--help") == "help"
    assert sanitize_query('foo" OR (bar*) = x') == "foo OR bar x"
    assert sanitize_query("!!!") == ""
    assert sanitize_query("") == ""


def test_sanitize_query_collapses_spaces_and_keeps_unicode() -> None:
    assert sanitize_query("  a   b  ") == "a b"
    assert sanitize_query("café 42") == "café 42"


def test_sanitize_query_caps_length() -> None:
    cleaned = sanitize_query("a" * 200)
    assert len(cleaned) == MAX_QUERY_CHARS


# --- search: runner contract ----------------------------------------------

def test_search_passes_argv_list_without_shell(tmp_path: Path) -> None:
    root = tmp_path / "Documents"
    root.mkdir()
    runner = FakeMdfind()
    FileSearch(roots=[root], runner=runner, mdfind=MDFIND).search("budget")

    assert len(runner.calls) == 1
    argv, kwargs = runner.calls[0]
    assert isinstance(argv, list)
    assert argv[0] == MDFIND
    assert "-onlyin" in argv
    assert argv[argv.index("-onlyin") + 1] == str(root.resolve())
    assert argv[-1] == "budget"
    assert not kwargs.get("shell", False)


def test_query_never_starts_with_dash(tmp_path: Path) -> None:
    root = tmp_path / "Documents"
    root.mkdir()
    runner = FakeMdfind()
    FileSearch(roots=[root], runner=runner, mdfind=MDFIND).search("--help")

    sent = runner.calls[0][0][-1]
    assert sent == "help"
    assert not sent.startswith("-")


def test_empty_sanitized_query_runs_nothing(tmp_path: Path) -> None:
    root = tmp_path / "Documents"
    root.mkdir()
    runner = FakeMdfind()
    assert FileSearch(roots=[root], runner=runner).search("!!!") == []
    assert runner.calls == []


def test_missing_root_is_skipped(tmp_path: Path) -> None:
    real = tmp_path / "Documents"
    real.mkdir()
    runner = FakeMdfind()
    FileSearch(roots=[tmp_path / "missing", real], runner=runner).search("budget")
    assert len(runner.calls) == 1
    assert runner.calls[0][0][runner.calls[0][0].index("-onlyin") + 1] == str(real.resolve())


# --- search: filtering -----------------------------------------------------

def test_search_drops_hidden_secret_and_excluded_paths(tmp_path: Path) -> None:
    root = tmp_path / "Documents"
    visible = _make(root, "visible.txt")
    hidden = [
        _make(root, ".secret/a.txt"),
        _make(root, ".env"),
        _make(root, "config/.env.local"),
        _make(root, "keys/server.pem"),
        _make(root, "keys/server.key"),
        _make(root, "keys/bundle.p12"),
        _make(root, "app/node_modules/pkg/index.js"),
        _make(root, "Library/prefs.txt"),
        _make(root, "certs/cert.txt"),
    ]
    lines = [str(visible)] + [str(p) for p in hidden]
    runner = FakeMdfind({str(root.resolve()): lines})

    results = FileSearch(roots=[root], runner=runner, max_results=20).search("budget")

    assert results == [{"path": str(visible.resolve()), "name": "visible.txt"}]


def test_search_drops_files_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = _make(tmp_path, "outside.txt")
    (root / "link.txt").symlink_to(outside)
    runner = FakeMdfind({
        str(root.resolve()): [
            "../outside.txt",
            str(outside),
            str(root / "link.txt"),
        ]
    })

    assert FileSearch(roots=[root], runner=runner).search("budget") == []


def test_search_tolerates_timeout_oserror_and_nonzero_exit(tmp_path: Path) -> None:
    timeout_root = tmp_path / "a"
    oserror_root = tmp_path / "b"
    nonzero_root = tmp_path / "c"
    good_root = tmp_path / "d"
    for root in (timeout_root, oserror_root, nonzero_root, good_root):
        root.mkdir()
    good_file = _make(good_root, "budget.txt")

    class ByRootRunner(FakeMdfind):
        def __call__(self, argv, **kwargs):
            root = argv[argv.index("-onlyin") + 1]
            if root == str(nonzero_root.resolve()):
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr="")
            return super().__call__(argv, **kwargs)

    runner = ByRootRunner(
        {str(good_root.resolve()): [str(good_file)]},
        errors_by_root={
            str(timeout_root.resolve()): subprocess.TimeoutExpired("mdfind", 5.0),
            str(oserror_root.resolve()): OSError("no mdfind"),
        },
    )

    results = FileSearch(
        roots=[timeout_root, oserror_root, nonzero_root, good_root],
        runner=runner,
        max_results=10,
    ).search("budget")

    assert [r["name"] for r in results] == ["budget.txt"]


def test_search_respects_max_results_and_dedupes(tmp_path: Path) -> None:
    root = tmp_path / "Documents"
    files = [_make(root, f"budget-{i}.txt") for i in range(10)]
    lines = [str(p) for p in files] + [str(files[0])]
    runner = FakeMdfind({str(root.resolve()): lines})

    results = FileSearch(roots=[root], runner=runner, max_results=3).search("budget")

    assert len(results) == 3
    assert len({r["path"] for r in results}) == 3


# --- snippet ---------------------------------------------------------------

def test_snippet_returns_first_matching_line_case_insensitive(tmp_path: Path) -> None:
    root = tmp_path / "Documents"
    notes = _make(root, "notes.md", "hello\nThe Quarterly Budget is here\nbye\n")
    search = FileSearch(roots=[root], runner=FakeMdfind())

    assert search.snippet(str(notes), "budget") == "The Quarterly Budget is here"


def test_snippet_cuts_long_lines_to_160_chars(tmp_path: Path) -> None:
    root = tmp_path / "Documents"
    notes = _make(root, "long.txt", "budget " + "x" * 300)
    search = FileSearch(roots=[root], runner=FakeMdfind())

    result = search.snippet(str(notes), "budget")
    assert result is not None
    assert len(result) == 160


def test_snippet_none_when_no_line_matches(tmp_path: Path) -> None:
    root = tmp_path / "Documents"
    notes = _make(root, "notes.txt", "nothing relevant here")
    assert FileSearch(roots=[root], runner=FakeMdfind()).snippet(str(notes), "budget") is None


def test_snippet_none_for_non_text_extension(tmp_path: Path) -> None:
    root = tmp_path / "Documents"
    png = _make(root, "pic.png", "budget")
    assert FileSearch(roots=[root], runner=FakeMdfind()).snippet(str(png), "budget") is None


def test_snippet_none_for_oversize_file(tmp_path: Path) -> None:
    root = tmp_path / "Documents"
    big = _make(root, "big.txt", "budget\n" + "x" * MAX_SNIPPET_BYTES)
    assert big.stat().st_size > MAX_SNIPPET_BYTES
    assert FileSearch(roots=[root], runner=FakeMdfind()).snippet(str(big), "budget") is None


def test_snippet_allows_file_exactly_at_size_limit(tmp_path: Path) -> None:
    root = tmp_path / "Documents"
    exact = _make(root, "exact.txt", "budget" + "x" * (MAX_SNIPPET_BYTES - 6))
    assert exact.stat().st_size == MAX_SNIPPET_BYTES
    result = FileSearch(roots=[root], runner=FakeMdfind()).snippet(str(exact), "budget")
    assert result is not None
    assert result.startswith("budget")


def test_snippet_none_for_excluded_files(tmp_path: Path) -> None:
    root = tmp_path / "Documents"
    env_file = _make(root, ".env.txt", "budget=1")
    hidden = _make(root, ".hidden/notes.txt", "budget")
    nested = _make(root, "app/node_modules/pkg/readme.md", "budget")
    search = FileSearch(roots=[root], runner=FakeMdfind())

    assert search.snippet(str(env_file), "budget") is None
    assert search.snippet(str(hidden), "budget") is None
    assert search.snippet(str(nested), "budget") is None


def test_snippet_none_for_file_outside_roots(tmp_path: Path) -> None:
    root = tmp_path / "Documents"
    root.mkdir()
    outside = _make(tmp_path, "outside.txt", "budget")
    assert FileSearch(roots=[root], runner=FakeMdfind()).snippet(str(outside), "budget") is None
