"""GitHub review requests and CI status through the `gh` CLI login (no token of ours).

Watches the repos worked on with Claude Code or Codex in the last 7 days, taken from the
sessions' working folders. Every command is an argv list run with subprocess.run; the runner is
injectable so tests never start a process. A failing latest CI run on a repo is reported once.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from typing import Any

Runner = Callable[[list[str]], tuple[int, str]]

MAX_REPOS = 8
COMMAND_TIMEOUT_SECONDS = 20.0
MAX_FAILURE_AGE_SECONDS = 24 * 3600.0
_REMOTE_RE = re.compile(r"github\.com[:/]+([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def default_runner(argv: list[str]) -> tuple[int, str]:
    """Run argv (never a shell) and return (exit code, stdout); 127 when the tool is missing."""
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            argv, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SECONDS, check=False
        )
    except FileNotFoundError:
        return 127, ""
    except (subprocess.TimeoutExpired, OSError):
        return 124, ""
    return done.returncode, done.stdout


def parse_remote(url: str) -> str | None:
    match = _REMOTE_RE.search(url.strip())
    return f"{match.group(1)}/{match.group(2)}" if match else None


class GitHubWatcher:
    def __init__(self, runner: Runner | None = None) -> None:
        self._run = runner or default_runner
        self._remote_cache: dict[str, str | None] = {}
        self._reported_failures: set[str] = set()
        self.state: dict[str, Any] = {"available": None, "repos": []}

    def repos_for(self, cwds: list[str]) -> list[str]:
        repos: list[str] = []
        for cwd in cwds:
            if not cwd:
                continue
            if cwd not in self._remote_cache:
                code, out = self._run(["git", "-C", cwd, "remote", "get-url", "origin"])
                self._remote_cache[cwd] = parse_remote(out) if code == 0 else None
            repo = self._remote_cache[cwd]
            if repo and repo not in repos:
                repos.append(repo)
        return repos[:MAX_REPOS]

    def _json(self, argv: list[str]) -> Any:
        code, out = self._run(argv)
        if code != 0:
            return None
        try:
            return json.loads(out)
        except ValueError:
            return None

    def poll(self, cwds: list[str], now: float) -> list[dict[str, Any]]:
        """Refresh `state`; return the CI failures not reported before (each reported once)."""
        code, _ = self._run(["gh", "auth", "status"])
        if code != 0:
            self.state = {"available": False, "repos": []}
            return []
        repos_out: list[dict[str, Any]] = []
        new_failures: list[dict[str, Any]] = []
        for repo in self.repos_for(cwds):
            if not _REPO_RE.fullmatch(repo):
                continue
            reviews = self._json(
                ["gh", "pr", "list", "--repo", repo, "--search", "review-requested:@me",
                 "--state", "open", "--limit", "10", "--json", "number,title,url"]
            )
            runs = self._json(
                ["gh", "run", "list", "--repo", repo, "--limit", "1",
                 "--json", "databaseId,status,conclusion,name,headBranch,url,createdAt"]
            )
            entry: dict[str, Any] = {"repo": repo, "reviews": [], "ci": None}
            for pr in reviews if isinstance(reviews, list) else []:
                if isinstance(pr, dict):
                    entry["reviews"].append(
                        {"number": pr.get("number"), "title": str(pr.get("title", ""))[:200], "url": pr.get("url")}
                    )
            run = runs[0] if isinstance(runs, list) and runs and isinstance(runs[0], dict) else None
            if run is not None:
                entry["ci"] = {
                    "name": str(run.get("name", ""))[:100],
                    "branch": str(run.get("headBranch", ""))[:100],
                    "status": run.get("status"),
                    "conclusion": run.get("conclusion"),
                    "url": run.get("url"),
                }
                run_id = str(run.get("databaseId"))
                if run.get("conclusion") == "failure" and f"{repo}#{run_id}" not in self._reported_failures:
                    self._reported_failures.add(f"{repo}#{run_id}")
                    from app.ai_coding.sessions import _ts

                    created = _ts(run.get("createdAt"))
                    if created is None or now - created <= MAX_FAILURE_AGE_SECONDS:
                        new_failures.append({"repo": repo, "run_id": run_id, "name": entry["ci"]["name"]})
            repos_out.append(entry)
        self.state = {"available": True, "repos": repos_out}
        return new_failures
