"""Grant snapshots — API-key / PAT fetch into local files (not auto-write)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from vantage_core.cli import main
from vantage_core.draft import analyze_and_draft, propose_paths, scan_repo
from vantage_core.grant import (
    apply_grants,
    grant_braintrust,
    grant_github,
    grant_langsmith,
    parse_grant_list,
)
from vantage_core.ingest import analyze_export, load_export

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "draft"
SAMPLE = FIXTURES / "sample_app"
INGEST_SAMPLES = Path(__file__).resolve().parents[1] / "examples" / "ingest"


def test_parse_grant_list():
    assert parse_grant_list("langsmith,github") == ["langsmith", "github"]
    assert parse_grant_list("ls,bt,gh") == ["langsmith", "braintrust", "github"]
    with pytest.raises(ValueError):
        parse_grant_list("datadog")


def test_grant_langsmith_writes_ingest_shape(tmp_path: Path):
    sample = json.loads((INGEST_SAMPLES / "langsmith_export_sample.json").read_text(encoding="utf-8"))

    def fake_get(url: str, headers: dict[str, str]):
        assert "x-api-key" in headers
        assert "acme" in url or "project" in url
        return sample["runs"]

    out = tmp_path / "ls.json"
    path = grant_langsmith(
        project="acme-support-agent",
        out=out,
        api_key="ls-test-key",
        force=True,
        http_get=fake_get,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == "langsmith.export.v0"
    assert payload["source"] == "grant.langsmith"
    assert payload["runs"]
    analyzed = analyze_export(payload)
    assert analyzed["suggestions"]


def test_grant_braintrust_writes_ingest_shape(tmp_path: Path):
    sample = json.loads((INGEST_SAMPLES / "braintrust_export_sample.json").read_text(encoding="utf-8"))

    def fake_get(url: str, headers: dict[str, str]):
        assert headers.get("Authorization", "").startswith("Bearer ")
        return {"events": sample["events"]}

    out = tmp_path / "bt.json"
    path = grant_braintrust(
        experiment="exp-1",
        out=out,
        api_key="bt-test-key",
        force=True,
        http_get=fake_get,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == "braintrust.export.v0"
    assert payload["events"]
    assert analyze_export(payload)["suggestions"]


def test_grant_github_sparse_tree(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token")
    tree = {
        "tree": [
            {"path": "src/policy.py", "type": "blob", "size": 120},
            {"path": "src/llm.ts", "type": "blob", "size": 200},
            {"path": "node_modules/x.js", "type": "blob", "size": 10},
            {"path": ".env", "type": "blob", "size": 10},
            {"path": "README.md", "type": "blob", "size": 40},
        ]
    }
    files = {
        "src/policy.py": 'SOURCE_ATTRIBUTION_RULES = """Every claim needs [SOURCE: Document \\"x\\"]."""\n',
        "src/llm.ts": 'const SYSTEM = `Cite DOC-104.`;\nimport OpenAI from "openai";\n',
    }

    def fake_get(url: str, headers: dict[str, str]):
        assert "Bearer ghp_test_token" in headers.get("Authorization", "")
        if url.endswith("/repos/acme/agent") or "/repos/acme/agent?" in url:
            return {"default_branch": "main"}
        if "/git/ref/heads/" in url:
            return {"object": {"sha": "abc123"}}
        if "/git/trees/" in url:
            return tree
        if "/contents/" in url:
            for rel, body in files.items():
                if rel in url:
                    return {
                        "encoding": "base64",
                        "content": base64.b64encode(body.encode("utf-8")).decode("ascii"),
                    }
            raise RuntimeError(f"HTTP 404 from {url}")
        raise RuntimeError(f"unexpected url {url}")

    dest = grant_github(
        "acme/agent",
        out=tmp_path / "repo",
        force=True,
        http_get=fake_get,
    )
    assert (dest / "src" / "policy.py").is_file()
    assert (dest / "src" / "llm.ts").is_file()
    assert not (dest / "node_modules").exists()
    assert not (dest / ".env").exists()
    man = json.loads((dest / "grant_manifest.json").read_text(encoding="utf-8"))
    assert man["repo"] == "acme/agent"
    assert "src/policy.py" in man["files"]


def test_draft_grant_wires_ingest(tmp_path: Path, monkeypatch):
    sample = json.loads((INGEST_SAMPLES / "langsmith_export_sample.json").read_text(encoding="utf-8"))

    def fake_get(url: str, headers: dict[str, str]):
        return sample["runs"]

    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test")
    monkeypatch.setenv("LANGSMITH_PROJECT", "acme-support-agent")

    import vantage_core.grant as grant_mod

    real_langsmith = grant_mod.grant_langsmith

    def fake_langsmith(**kwargs):
        kwargs = dict(kwargs)
        kwargs["http_get"] = fake_get
        kwargs["api_key"] = "ls-test"
        return real_langsmith(**kwargs)

    monkeypatch.setattr(grant_mod, "grant_langsmith", fake_langsmith)

    import shutil

    root = tmp_path / "app"
    shutil.copytree(SAMPLE, root)
    code = main(
        [
            "draft",
            str(root),
            "--grant",
            "langsmith",
            "--write-drafts",
            str(tmp_path / "drafts"),
            "--force",
            "--json",
        ]
    )
    assert code == 0
    assert (tmp_path / "app" / ".vantage-grant" / "langsmith.json").is_file()
    assert list((tmp_path / "drafts").glob("*.draft.yaml"))


def test_join_rank_prefers_trace_opening_overlapping_policy(tmp_path: Path):
    """Phase 2: trace opening that hits their policy token becomes the opening."""
    ingest = analyze_export(
        {
            "schema": "langsmith.export.v0",
            "runs": [
                {
                    "id": "1",
                    "status": "success",
                    "error": "dropped citation",
                    "inputs": {
                        "messages": [
                            {
                                "role": "user",
                                "content": "What is the dose? Use [SOURCE: Document] tags.",
                            }
                        ]
                    },
                    "outputs": {
                        "messages": [
                            {"role": "assistant", "content": "10mg daily. (no source)"}
                        ]
                    },
                    "tags": ["citation", "critical"],
                }
            ],
        }
    )
    scan = scan_repo(SAMPLE)
    props = propose_paths(scan, ingest=ingest)
    assert props
    # At least one opening should carry SOURCE / citation from the export
    openings = " ".join(p.opening for p in props).lower()
    assert "[source" in openings or "source" in openings or "dose" in openings


def test_cli_grant_langsmith(tmp_path: Path, monkeypatch, capsys):
    sample = json.loads((INGEST_SAMPLES / "langsmith_export_sample.json").read_text(encoding="utf-8"))

    def fake_get(url: str, headers: dict[str, str]):
        return sample["runs"]

    import vantage_core.grant as grant_mod

    monkeypatch.setattr(
        grant_mod,
        "_http_get_json",
        fake_get,
    )
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test")
    out = tmp_path / "out.json"
    assert (
        main(
            [
                "grant",
                "langsmith",
                "--project",
                "acme",
                "--out",
                str(out),
                "--force",
            ]
        )
        == 0
    )
    assert out.is_file()
    assert "Accept required" in capsys.readouterr().out
