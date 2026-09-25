"""Grant snapshots — fetch authorized artifacts onto their machine.

API keys / PAT / ``gh`` stay local. Writes the same file shapes ``draft`` and
``ingest`` already read. Never auto-writes the bar; Accept is still required.

Not hosted OAuth (token with us) — that is paid-later.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from vantage_core.draft import (
    CODE_SUFFIXES,
    SKIP_DIRS,
    SKIP_NAMES,
    SKIP_SUFFIXES,
    _is_probably_minified,
    _is_test_file,
)

GRANT_DIR = ".vantage-grant"
LANGSMITH_API = "https://api.smith.langchain.com"
BRAINTRUST_API = "https://api.braintrust.dev"
GITHUB_API = "https://api.github.com"

HttpGet = Callable[[str, dict[str, str]], Any]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_grant_dir(root: str | Path | None = None) -> Path:
    base = Path(root or Path.cwd()).expanduser().resolve()
    return base / GRANT_DIR


def _http_get_json(url: str, headers: dict[str, str], *, timeout: float = 60.0) -> Any:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network error fetching {url}: {exc}") from exc
    if not raw.strip():
        return None
    return json.loads(raw)


def _write_json(path: Path, payload: dict[str, Any], *, force: bool = False) -> Path:
    path = path.expanduser().resolve()
    if path.exists() and not force:
        raise FileExistsError(f"refusing to overwrite {path} (pass --force)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# LangSmith
# ---------------------------------------------------------------------------


def grant_langsmith(
    *,
    project: str,
    out: str | Path,
    api_key: str | None = None,
    limit: int = 100,
    force: bool = False,
    http_get: HttpGet | None = None,
) -> Path:
    """One-shot LangSmith runs dump → ingest-shaped JSON. Key: LANGSMITH_API_KEY."""
    key = (api_key or os.environ.get("LANGSMITH_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "LANGSMITH_API_KEY required for grant langsmith "
            "(export on your machine — we do not store it)"
        )
    getter = http_get or _http_get_json
    headers = {"x-api-key": key, "Accept": "application/json"}
    # Prefer query endpoint; fall back to list with project filter.
    q = urllib.parse.urlencode(
        {
            "project_name": project,
            "limit": str(max(1, min(int(limit), 500))),
        }
    )
    url = f"{LANGSMITH_API}/runs?{q}"
    data = getter(url, headers)
    runs: list[dict[str, Any]] = []
    if isinstance(data, list):
        runs = [r for r in data if isinstance(r, dict)]
    elif isinstance(data, dict):
        for key_name in ("runs", "results", "data"):
            if isinstance(data.get(key_name), list):
                runs = [r for r in data[key_name] if isinstance(r, dict)]
                break
        if not runs and data.get("id"):
            runs = [data]
    payload = {
        "schema": "langsmith.export.v0",
        "note": "Snapshot from vantage-core grant langsmith — not a live sync.",
        "project": project,
        "fetched_at": _now_iso(),
        "source": "grant.langsmith",
        "runs": runs,
    }
    return _write_json(Path(out), payload, force=force)


# ---------------------------------------------------------------------------
# Braintrust
# ---------------------------------------------------------------------------


def grant_braintrust(
    *,
    experiment: str,
    out: str | Path,
    api_key: str | None = None,
    limit: int = 100,
    force: bool = False,
    http_get: HttpGet | None = None,
) -> Path:
    """One-shot Braintrust experiment events → ingest-shaped JSON.

    Key: BRAINTRUST_API_KEY. ``experiment`` is an experiment id or name slug.
    """
    key = (api_key or os.environ.get("BRAINTRUST_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "BRAINTRUST_API_KEY required for grant braintrust "
            "(export on your machine — we do not store it)"
        )
    getter = http_get or _http_get_json
    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }
    exp = urllib.parse.quote(experiment, safe="")
    q = urllib.parse.urlencode({"limit": str(max(1, min(int(limit), 500)))})
    url = f"{BRAINTRUST_API}/v1/experiment/{exp}/fetch?{q}"
    try:
        data = getter(url, headers)
    except RuntimeError:
        # Alternate shape: /v1/experiment/{id}/events
        url = f"{BRAINTRUST_API}/v1/experiment/{exp}/events?{q}"
        data = getter(url, headers)

    events: list[dict[str, Any]] = []
    if isinstance(data, list):
        events = [e for e in data if isinstance(e, dict)]
    elif isinstance(data, dict):
        for key_name in ("events", "rows", "data", "objects"):
            if isinstance(data.get(key_name), list):
                events = [e for e in data[key_name] if isinstance(e, dict)]
                break
    payload = {
        "schema": "braintrust.export.v0",
        "note": "Snapshot from vantage-core grant braintrust — not a live sync.",
        "project": experiment,
        "fetched_at": _now_iso(),
        "source": "grant.braintrust",
        "events": events,
    }
    return _write_json(Path(out), payload, force=force)


# ---------------------------------------------------------------------------
# GitHub sparse tree
# ---------------------------------------------------------------------------


def _github_token(explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    for env in ("GITHUB_TOKEN", "GH_TOKEN"):
        val = (os.environ.get(env) or "").strip()
        if val:
            return val
    # Fall back to `gh auth token` when available.
    try:
        proc = subprocess.run(
            ["gh", "auth", "token"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    raise RuntimeError(
        "GITHUB_TOKEN (or GH_TOKEN / `gh auth token`) required for grant github "
        "(token stays on your machine — we do not store it)"
    )


def _should_skip_github_path(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    for part in parts[:-1]:
        if part in SKIP_DIRS or part.startswith("."):
            if part not in {".github"}:  # allow .github workflows? skip hidden dirs
                if part.startswith(".") and part != ".github":
                    return True
                if part in SKIP_DIRS:
                    return True
    name = parts[-1] if parts else ""
    if name in SKIP_NAMES:
        return True
    if name.startswith(".env"):
        return True
    low = name.lower()
    for suf in SKIP_SUFFIXES:
        if low.endswith(suf):
            return True
    # Keep only scannable code / test / policy-ish text
    suffix = Path(name).suffix.lower()
    if suffix and suffix not in CODE_SUFFIXES and suffix not in {
        ".md",
        ".txt",
        ".yaml",
        ".yml",
        ".json",
        ".toml",
        ".html",
    }:
        return True
    return False


def _looks_scannable(path: str) -> bool:
    """Keep files draft.scan_repo would care about."""
    p = Path(path)
    name = p.name
    suffix = p.suffix.lower()
    if _is_test_file(p):
        return True
    if suffix in CODE_SUFFIXES:
        return True
    if suffix in {".md", ".txt", ".yaml", ".yml", ".html"}:
        # Policy / prompt docs
        low = name.lower()
        if any(tok in low for tok in ("policy", "prompt", "system", "agent", "rule")):
            return True
    return False


def grant_github(
    repo: str,
    *,
    out: str | Path,
    path: str = "",
    ref: str | None = None,
    token: str | None = None,
    force: bool = False,
    http_get: HttpGet | None = None,
    max_files: int = 200,
) -> Path:
    """Sparse GitHub tree → local directory for ``draft`` to scan.

    ``repo`` is ``owner/name``. Uses Contents/Git Trees API — not a full clone.
    """
    m = re.fullmatch(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", repo.strip())
    if not m:
        raise ValueError("repo must be owner/name")
    owner, name = m.group(1), m.group(2)
    tok = _github_token(token)
    getter = http_get or _http_get_json
    headers = {
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "vantage-core-grant",
    }

    dest = Path(out).expanduser().resolve()
    if dest.exists() and any(dest.iterdir()) and not force:
        raise FileExistsError(f"refusing to overwrite non-empty {dest} (pass --force)")
    dest.mkdir(parents=True, exist_ok=True)

    # Resolve default branch / commit SHA
    repo_url = f"{GITHUB_API}/repos/{owner}/{name}"
    meta = getter(repo_url, headers)
    if not isinstance(meta, dict):
        raise RuntimeError(f"unexpected GitHub repo payload for {repo}")
    default_branch = str(meta.get("default_branch") or "main")
    branch = ref or default_branch
    ref_url = f"{GITHUB_API}/repos/{owner}/{name}/git/ref/heads/{urllib.parse.quote(branch)}"
    try:
        ref_payload = getter(ref_url, headers)
        sha = str((ref_payload or {}).get("object", {}).get("sha") or "")
    except RuntimeError:
        # Tag or bare SHA
        sha = branch
    if not sha:
        commit_url = f"{GITHUB_API}/repos/{owner}/{name}/commits/{urllib.parse.quote(branch)}"
        commit = getter(commit_url, headers)
        sha = str((commit or {}).get("sha") or "")
    if not sha:
        raise RuntimeError(f"could not resolve ref {branch!r} for {repo}")

    tree_url = f"{GITHUB_API}/repos/{owner}/{name}/git/trees/{sha}?recursive=1"
    tree_payload = getter(tree_url, headers)
    entries = list((tree_payload or {}).get("tree") or [])
    prefix = path.strip("/").replace("\\", "/")
    written: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "blob":
            continue
        rel = str(entry.get("path") or "")
        if not rel:
            continue
        if prefix and not (rel == prefix or rel.startswith(prefix + "/")):
            continue
        if _should_skip_github_path(rel):
            continue
        if not _looks_scannable(rel):
            continue
        # Size guard
        try:
            size = int(entry.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        if size > 512_000:
            continue
        file_url = f"{GITHUB_API}/repos/{owner}/{name}/contents/{urllib.parse.quote(rel)}?ref={urllib.parse.quote(sha)}"
        try:
            file_payload = getter(file_url, headers)
        except RuntimeError:
            continue
        if not isinstance(file_payload, dict):
            continue
        content_b64 = str(file_payload.get("content") or "")
        encoding = str(file_payload.get("encoding") or "")
        if encoding != "base64" or not content_b64:
            continue
        try:
            text = base64.b64decode(content_b64).decode("utf-8", errors="replace")
        except (ValueError, TypeError):
            continue
        target = dest / rel
        if _is_probably_minified(target) and len(text) > 20_000 and text.count("\n") < 30:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written.append(rel)
        if len(written) >= max_files:
            break

    manifest = {
        "schema": "runtimeai.grant_github/v1",
        "repo": f"{owner}/{name}",
        "ref": branch,
        "sha": sha,
        "path": prefix or None,
        "fetched_at": _now_iso(),
        "files": written,
        "claim": (
            "Sparse GitHub snapshot for draft. Accept required. "
            "Not a full clone. Not hosted OAuth. Not auto-write."
        ),
    }
    (dest / "grant_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return dest


# ---------------------------------------------------------------------------
# Combined grant for draft --grant
# ---------------------------------------------------------------------------


def parse_grant_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for part in str(raw).split(","):
        tok = part.strip().lower()
        if not tok:
            continue
        if tok in {"ls", "langsmith"}:
            out.append("langsmith")
        elif tok in {"bt", "braintrust"}:
            out.append("braintrust")
        elif tok in {"gh", "github"}:
            out.append("github")
        else:
            raise ValueError(
                f"unknown grant source {part!r} — use langsmith, braintrust, github"
            )
    # stable unique order
    seen: set[str] = set()
    uniq: list[str] = []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def apply_grants(
    sources: list[str],
    *,
    root: str | Path = ".",
    github_repo: str | None = None,
    langsmith_project: str | None = None,
    braintrust_experiment: str | None = None,
    github_path: str = "",
    github_ref: str | None = None,
    force: bool = True,
    http_get: HttpGet | None = None,
) -> dict[str, Any]:
    """Fetch selected snapshots into ``.vantage-grant/`` under root.

    Returns paths usable by ``analyze_and_draft`` (``repo`` override and/or ``ingest``).
    """
    work = default_grant_dir(root)
    work.mkdir(parents=True, exist_ok=True)
    # Ensure local gitignore entry for the grant cache
    _ensure_gitignore(Path(root).expanduser().resolve())

    result: dict[str, Any] = {
        "grant_dir": str(work),
        "sources": list(sources),
        "ingest": None,
        "repo": None,
        "files": [],
        "claim": (
            "Grant snapshot — connect once, snapshot, Accept. "
            "Not auto-write. Tokens stay on your machine."
        ),
    }
    for src in sources:
        if src == "langsmith":
            project = (langsmith_project or os.environ.get("LANGSMITH_PROJECT") or "").strip()
            if not project:
                raise RuntimeError(
                    "grant langsmith needs --langsmith-project or LANGSMITH_PROJECT"
                )
            path = grant_langsmith(
                project=project,
                out=work / "langsmith.json",
                force=force,
                http_get=http_get,
            )
            result["ingest"] = str(path)
            result["files"].append(str(path))
        elif src == "braintrust":
            experiment = (
                braintrust_experiment or os.environ.get("BRAINTRUST_EXPERIMENT") or ""
            ).strip()
            if not experiment:
                raise RuntimeError(
                    "grant braintrust needs --braintrust-experiment or BRAINTRUST_EXPERIMENT"
                )
            path = grant_braintrust(
                experiment=experiment,
                out=work / "braintrust.json",
                force=force,
                http_get=http_get,
            )
            # Prefer langsmith if both; else braintrust becomes ingest
            if not result["ingest"]:
                result["ingest"] = str(path)
            result["files"].append(str(path))
        elif src == "github":
            repo = (github_repo or os.environ.get("GITHUB_REPOSITORY") or "").strip()
            if not repo:
                raise RuntimeError(
                    "grant github needs --github-repo owner/name or GITHUB_REPOSITORY"
                )
            dest = grant_github(
                repo,
                out=work / "repo",
                path=github_path,
                ref=github_ref,
                force=force,
                http_get=http_get,
            )
            result["repo"] = str(dest)
            result["files"].append(str(dest))
    return result


def _ensure_gitignore(root: Path) -> None:
    gi = root / ".gitignore"
    line = f"{GRANT_DIR}/"
    try:
        if gi.is_file():
            text = gi.read_text(encoding="utf-8")
            if GRANT_DIR in text:
                return
            with gi.open("a", encoding="utf-8") as fh:
                if text and not text.endswith("\n"):
                    fh.write("\n")
                fh.write(f"# vantage-core grant snapshots (local secrets/cache)\n{line}\n")
        else:
            gi.write_text(
                f"# vantage-core grant snapshots (local secrets/cache)\n{line}\n",
                encoding="utf-8",
            )
    except OSError:
        pass
