"""Post bind + still-trust compare onto the PR / MR.

Not a review UI. One living comment per check (updated in place).
Uses GITHUB_TOKEN / GitLab job token — no GitHub App.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from vantage_core import __version__

MARKER = "<!-- vantage-core-decision -->"


def _first_env(*names: str) -> str | None:
    for name in names:
        val = (os.getenv(name) or "").strip()
        if val:
            return val
    return None


def format_comment(decision: dict[str, Any]) -> str:
    """Markdown for a PR/MR: bind, route, compare_to_baseline."""
    gate = decision.get("pass_gate") if isinstance(decision.get("pass_gate"), dict) else {}
    bind = decision.get("bind") if isinstance(decision.get("bind"), dict) else {}
    suite = decision.get("suite") if isinstance(decision.get("suite"), dict) else {}
    cmp = (
        decision.get("compare_to_baseline")
        if isinstance(decision.get("compare_to_baseline"), dict)
        else {}
    )
    route = str(gate.get("route") or ("pass" if decision.get("passed") else "block"))
    exit_code = decision.get("exit_code")
    if exit_code is None:
        exit_obj = decision.get("exit") if isinstance(decision.get("exit"), dict) else {}
        exit_code = exit_obj.get("code")
    score = decision.get("out_of_10")
    score_s = f"{float(score):.1f} / 10" if isinstance(score, (int, float)) else "n/a"
    cost = decision.get("est_usd")
    cost_s = f"~${float(cost):.4f}" if isinstance(cost, (int, float)) else "n/a"
    headline = str(bind.get("headline") or "").strip() or "SHA unknown — bind skipped"
    suite_id = str(suite.get("id") or decision.get("scenario_id") or "—")
    if suite:
        paths = f"{suite.get('passed_count')}/{suite.get('path_count')} paths"
        suite_line = f"{suite_id} · {paths}"
    else:
        suite_line = suite_id
    gate_line = str(gate.get("headline") or "").strip()

    lines = [
        MARKER,
        "## RuntimeAI still-trust",
        "",
        f"**{headline}**",
        "",
        f"| | |",
        f"|---|---|",
        f"| Route | `{route}` · exit `{exit_code}` |",
        f"| Score | {score_s} |",
        f"| Cost | {cost_s} |",
        f"| Suite | {suite_line} |",
    ]
    if gate_line:
        lines.extend(["", gate_line])
    if cmp:
        lines.extend(["", "### vs last ship"])
        if cmp.get("headline"):
            lines.append(str(cmp["headline"]))
        transition = cmp.get("gate_transition")
        if transition:
            lines.append(f"Gate: `{transition}`")
        if cmp.get("score_delta") is not None:
            lines.append(f"Δscore {float(cmp['score_delta']):+.1f}")
        if cmp.get("cost_delta_usd") is not None:
            lines.append(f"Δcost ${float(cmp['cost_delta_usd']):+.4f}")
        regs = cmp.get("paths_regressed") or cmp.get("regressions") or []
        fixes = cmp.get("paths_improved") or cmp.get("fixes") or []
        for cid in regs:
            lines.append(f"- regressed: `{cid}`")
        for cid in fixes:
            lines.append(f"- improved: `{cid}`")
    lines.extend(
        [
            "",
            "Exit is the **current** gate (not “same as last ship”). "
            "`runtimeai.decision/v1` artifact — not a trace UI.",
        ]
    )
    return "\n".join(lines) + "\n"


def _http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> Any:
    data = None
    hdrs = dict(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code} {method} {url}: {detail}") from exc


def post_github_comment(
    body: str,
    *,
    token: str | None = None,
    repo: str | None = None,
    pr_number: int | None = None,
    api_url: str | None = None,
) -> dict[str, Any]:
    token = token or _first_env("GITHUB_TOKEN", "GH_TOKEN")
    repo = repo or _first_env("GITHUB_REPOSITORY")
    api_url = (api_url or _first_env("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
    if pr_number is None:
        raw = _first_env("VANTAGE_PR_NUMBER", "GITHUB_PR_NUMBER")
        if raw:
            try:
                pr_number = int(raw)
            except ValueError:
                pr_number = None
    if pr_number is None:
        from vantage_core.bind import resolve_bind

        bind = resolve_bind() or {}
        if bind.get("pr_number") is not None:
            pr_number = int(bind["pr_number"])
    if not token or not repo or pr_number is None:
        raise RuntimeError(
            "GitHub comment needs GITHUB_TOKEN, GITHUB_REPOSITORY, and a PR number"
        )
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"vantage-core/{__version__}",
    }
    encoded_repo = "/".join(urllib.parse.quote(p, safe="") for p in repo.split("/", 1))
    list_url = f"{api_url}/repos/{encoded_repo}/issues/{int(pr_number)}/comments?per_page=100"
    comments = _http_json("GET", list_url, headers=headers)
    if not isinstance(comments, list):
        comments = []
    existing_id = None
    for item in comments:
        if not isinstance(item, dict):
            continue
        if MARKER in str(item.get("body") or ""):
            existing_id = item.get("id")
            break
    if existing_id is not None:
        url = f"{api_url}/repos/{encoded_repo}/issues/comments/{existing_id}"
        result = _http_json("PATCH", url, headers=headers, body={"body": body})
        action = "updated"
    else:
        url = f"{api_url}/repos/{encoded_repo}/issues/{int(pr_number)}/comments"
        result = _http_json("POST", url, headers=headers, body={"body": body})
        action = "created"
    html = ""
    if isinstance(result, dict):
        html = str(result.get("html_url") or "")
    return {"action": action, "html_url": html, "pr_number": int(pr_number)}


def post_gitlab_comment(
    body: str,
    *,
    token: str | None = None,
    api_url: str | None = None,
    project_id: str | None = None,
    mr_iid: int | None = None,
) -> dict[str, Any]:
    token = token or _first_env("GITLAB_TOKEN", "CI_JOB_TOKEN")
    job_token = bool(_first_env("CI_JOB_TOKEN")) and not _first_env("GITLAB_TOKEN")
    api_url = (api_url or _first_env("CI_API_V4_URL") or "https://gitlab.com/api/v4").rstrip(
        "/"
    )
    project_id = project_id or _first_env("CI_PROJECT_ID")
    if mr_iid is None:
        raw = _first_env("CI_MERGE_REQUEST_IID", "VANTAGE_PR_NUMBER")
        if raw:
            try:
                mr_iid = int(raw)
            except ValueError:
                mr_iid = None
    if not token or not project_id or mr_iid is None:
        raise RuntimeError(
            "GitLab comment needs GITLAB_TOKEN or CI_JOB_TOKEN, CI_PROJECT_ID, "
            "and CI_MERGE_REQUEST_IID"
        )
    headers = {
        "User-Agent": f"vantage-core/{__version__}",
    }
    if job_token:
        headers["JOB-TOKEN"] = token
    else:
        headers["PRIVATE-TOKEN"] = token
    pid = urllib.parse.quote(str(project_id), safe="")
    list_url = f"{api_url}/projects/{pid}/merge_requests/{int(mr_iid)}/notes?per_page=100"
    notes = _http_json("GET", list_url, headers=headers)
    if not isinstance(notes, list):
        notes = []
    existing_id = None
    for item in notes:
        if not isinstance(item, dict):
            continue
        if MARKER in str(item.get("body") or ""):
            existing_id = item.get("id")
            break
    if existing_id is not None:
        url = f"{api_url}/projects/{pid}/merge_requests/{int(mr_iid)}/notes/{existing_id}"
        result = _http_json("PUT", url, headers=headers, body={"body": body})
        action = "updated"
    else:
        url = f"{api_url}/projects/{pid}/merge_requests/{int(mr_iid)}/notes"
        result = _http_json("POST", url, headers=headers, body={"body": body})
        action = "created"
    html = ""
    if isinstance(result, dict):
        html = str(result.get("web_url") or "")
    return {"action": action, "html_url": html, "mr_iid": int(mr_iid)}


def detect_ci_host() -> str | None:
    if (os.getenv("GITHUB_ACTIONS") or "").lower() in ("1", "true"):
        return "github"
    if (os.getenv("GITLAB_CI") or "").lower() in ("1", "true"):
        return "gitlab"
    return None


def maybe_post_ci_comment(
    decision: dict[str, Any],
    *,
    enabled: bool,
    comment_file: str | None = None,
    host: str | None = None,
) -> dict[str, Any] | None:
    """Write markdown and/or post to the current CI host. Never fails the gate."""
    if not enabled and not comment_file:
        return None
    body = format_comment(decision)
    result: dict[str, Any] = {"markdown": body}
    if comment_file:
        from pathlib import Path

        path = Path(comment_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        result["file"] = str(path.resolve())
    if not enabled:
        return result
    host = host or detect_ci_host()
    try:
        if host == "github":
            posted = post_github_comment(body)
            result.update(posted)
            result["host"] = "github"
        elif host == "gitlab":
            posted = post_gitlab_comment(body)
            result.update(posted)
            result["host"] = "gitlab"
        else:
            result["skipped"] = "not in GitHub Actions or GitLab CI"
    except Exception as exc:
        result["error"] = str(exc)
    return result
