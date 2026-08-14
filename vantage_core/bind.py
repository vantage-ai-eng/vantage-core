"""Release bind — attach decision/v1 to git SHA / PR when known.

Populated from CI env (GitHub Actions, GitLab CI) or local ``git rev-parse``.
Bind is optional: when no SHA is known, decisions omit the ``bind`` block.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

_PR_REF_RE = re.compile(r"refs/pull/(\d+)/")


def _first_env(*names: str) -> str | None:
    for name in names:
        val = (os.getenv(name) or "").strip()
        if val:
            return val
    return None


def _git_rev_parse(cwd: Path | None = None) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd or Path.cwd()),
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    sha = (proc.stdout or "").strip()
    return sha[:40] if sha else None


def _pr_from_ref(ref: str | None) -> int | None:
    if not ref:
        return None
    m = _PR_REF_RE.search(ref)
    if m:
        return int(m.group(1))
    return None


def _pr_from_event_path() -> tuple[int | None, str | None]:
    """Parse GITHUB_EVENT_PATH for pull_request number + html_url."""
    path = (os.getenv("GITHUB_EVENT_PATH") or "").strip()
    if not path:
        return None, None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    pr = data.get("pull_request") if isinstance(data.get("pull_request"), dict) else None
    if pr:
        num = pr.get("number")
        url = pr.get("html_url")
        return (int(num) if num is not None else None), (str(url) if url else None)
    # Some workflows put number at top level
    num = data.get("number")
    if num is not None and data.get("action"):
        try:
            return int(num), None
        except (TypeError, ValueError):
            pass
    return None, None


def _detect_source(*, sha_from_env: bool, sha_from_git: bool) -> str | None:
    if (os.getenv("GITHUB_ACTIONS") or "").lower() in ("1", "true"):
        return "github_actions"
    if (os.getenv("GITLAB_CI") or "").lower() in ("1", "true"):
        return "gitlab_ci"
    if (os.getenv("CI") or "").lower() in ("1", "true"):
        return "ci"
    if sha_from_env:
        return "env"
    if sha_from_git:
        return "git"
    return None


def resolve_bind(*, cwd: Path | None = None, generated_at: str | None = None) -> dict[str, Any] | None:
    """Return a bind block when a git SHA is known; otherwise None."""
    env_sha = _first_env("VANTAGE_GIT_SHA", "GITHUB_SHA", "CI_COMMIT_SHA")
    sha_from_env = bool(env_sha)
    sha = env_sha
    sha_from_git = False
    if not sha:
        sha = _git_rev_parse(cwd)
        sha_from_git = bool(sha)
    if not sha:
        return None

    ref = _first_env(
        "VANTAGE_GIT_REF",
        "GITHUB_REF",
        "GITHUB_HEAD_REF",
        "GITHUB_REF_NAME",
        "CI_COMMIT_REF_NAME",
    )
    pr_number = None
    pr_url = None
    raw_pr = _first_env("VANTAGE_PR_NUMBER", "GITHUB_PR_NUMBER")
    if raw_pr:
        try:
            pr_number = int(raw_pr)
        except ValueError:
            pr_number = None
    if pr_number is None:
        pr_number = _pr_from_ref(ref)
    if pr_number is None:
        event_pr, event_url = _pr_from_event_path()
        pr_number = event_pr
        pr_url = event_url

    short = sha[:7] if len(sha) >= 7 else sha
    when = generated_at or "now"
    if pr_number is not None:
        headline = f"PR #{pr_number} / SHA {short} decided at {when}"
    else:
        headline = f"SHA {short} decided at {when}"

    bind: dict[str, Any] = {
        "git_sha": sha,
        "git_sha_short": short,
        "git_ref": ref,
        "pr_number": pr_number,
        "pr_url": pr_url,
        "source": _detect_source(sha_from_env=sha_from_env, sha_from_git=sha_from_git),
        "headline": headline,
    }
    return bind
