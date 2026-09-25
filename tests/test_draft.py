"""Authorized custom draft — scan their artifacts, not library IDs."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from vantage_core.cli import main
from vantage_core.draft import (
    LIBRARY_IDS,
    analyze_and_draft,
    propose_paths,
    scan_repo,
    write_drafts,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "draft"
SAMPLE = FIXTURES / "sample_app"
BEATIT = FIXTURES / "beatit_slice"


def test_scan_skips_node_modules_and_env(tmp_path: Path):
    # .env is gitignored, so it cannot be a checked-in fixture. In a fresh clone the
    # assertion below passed because the file was absent, not because scan_repo skipped
    # it - the test was green and testing nothing. Write it here so there is always
    # something to skip.
    app = tmp_path / "sample_app"
    shutil.copytree(SAMPLE, app)
    (app / ".env").write_text(
        "OPENROUTER_API_KEY=sk-or-v1-THIS-MUST-NOT-APPEAR-IN-DRAFTS\n"
        "OPENAI_API_KEY=sk-ant-THIS-MUST-NOT-APPEAR-EITHER\n",
        encoding="utf-8",
    )
    assert (app / ".env").is_file()

    scan = scan_repo(app)
    # Compare paths relative to the scan root. The absolute tmp_path contains the test
    # name, which contains "node_modules", and would satisfy the substring assertion
    # below on its own.
    rels = []
    for q in [s.path for s in scan.strings] + [o.path for o in scan.oracles]:
        try:
            rel = Path(q).resolve().relative_to(app.resolve())
        except ValueError:
            rel = Path(q)
        rels.append(str(rel).replace("\\", "/"))
    blob = " ".join(rels)
    assert "node_modules" not in blob
    assert ".env" not in blob
    assert scan.llm_sites
    assert any("SOURCE_ATTRIBUTION" in s.name for s in scan.strings)
    assert any("PALLIATIVE" in s.name for s in scan.strings)
    assert any(o.literal == "DOC-104" for o in scan.oracles)


def test_scan_skips_local_data_and_patients_dirs(tmp_path: Path):
    """Never draft from local PHI / app data trees (e.g. beatit/data/patients)."""
    app = tmp_path / "app"
    (app / "src").mkdir(parents=True)
    (app / "data" / "patients" / "alice").mkdir(parents=True)
    (app / "uploads").mkdir(parents=True)
    (app / "src" / "policy.py").write_text(
        'SYSTEM_PROMPT = "You must cite [SOURCE: DOC-1]. Never invent labs."\n'
        "import openai\n"
        "client.chat.completions.create({})\n",
        encoding="utf-8",
    )
    (app / "data" / "patients" / "alice" / "notes.py").write_text(
        'SECRET_PATIENT = "Alice has stage IV — do not ship this file into drafts."\n'
        "import openai\n",
        encoding="utf-8",
    )
    (app / "uploads" / "scan.py").write_text(
        'UPLOAD_SECRET = "MRI report PHI"\nimport openai\n',
        encoding="utf-8",
    )
    scan = scan_repo(app)
    paths = " ".join(str(s.path) for s in scan.strings + scan.llm_sites)
    assert "policy.py" in paths or any("SYSTEM" in s.name for s in scan.strings)
    assert "alice" not in paths
    assert "SECRET_PATIENT" not in " ".join(s.value for s in scan.strings)
    assert "UPLOAD_SECRET" not in " ".join(s.value for s in scan.strings)
    assert "MRI report PHI" not in " ".join(s.value for s in scan.strings)


def test_custom_ids_from_their_strings_not_library(tmp_path: Path):
    result = analyze_and_draft(
        SAMPLE,
        write_dir=tmp_path / "contracts_drafts",
        force=True,
    )
    drafts = result["drafts"]
    assert 3 <= len(drafts) <= 5
    ids = [d["id"] for d in drafts]
    names = " ".join(d.get("name") or "" for d in drafts)
    joined = " ".join(ids).lower()
    for lib in LIBRARY_IDS:
        assert lib not in joined
        assert lib not in names.lower()
    assert any("source" in i or "attribution" in i or "palliative" in i or "exclusion" in i for i in joined.split())
    yaml_blob = ""
    for p in (tmp_path / "contracts_drafts").glob("*.draft.yaml"):
        yaml_blob += p.read_text(encoding="utf-8")
    assert "schema: runtimeai.contract/v1" in yaml_blob
    assert "kind: hard_checks" in yaml_blob
    assert "DOC-104" in yaml_blob
    assert "[SOURCE:" in yaml_blob
    assert "palliative" in yaml_blob.lower()
    assert "sk-or-" not in yaml_blob
    assert "sk-ant-" not in yaml_blob
    assert "THIS-MUST-NOT-APPEAR" not in yaml_blob
    assert "status: draft" in yaml_blob
    bodies = []
    for p in (tmp_path / "contracts_drafts").glob("*.draft.yaml"):
        text = p.read_text(encoding="utf-8")
        if "system: |" in text:
            bodies.append(re.sub(r"\s+", " ", text.split("system: |", 1)[1][:160]))
    assert len(bodies) == len(set(bodies))


def test_beatit_slice_refuse_aware_none_of(tmp_path: Path):
    result = analyze_and_draft(
        BEATIT,
        write_dir=tmp_path / "drafts",
        force=True,
    )
    blob = ""
    for p in (tmp_path / "drafts").glob("*.yaml"):
        blob += p.read_text(encoding="utf-8")
    assert "schema: runtimeai.contract/v1" in blob
    assert "healthcare_prior_auth_v1" not in blob
    assert "de_sql_optimization_v1" not in blob
    # Absolute exclusion may hard-fail palliative.
    assert "palliative" in blob.lower()
    # Bare staging topic must not be a refuse-trap none_of.
    assert 'none_of: ["stage iv"]' not in blob.lower()
    assert "none_of: [\"stage iv\"]" not in blob.lower()


def test_accept_moves_draft_and_updates_suite(tmp_path: Path):
    drafts = tmp_path / "contracts_drafts"
    analyze_and_draft(SAMPLE, write_dir=drafts, force=True)
    man = json.loads((drafts / "draft_manifest.json").read_text(encoding="utf-8"))
    first = man["drafts"][0]
    code = main(
        [
            "draft",
            "accept",
            first["id"],
            "--write-drafts",
            str(drafts),
            "--into",
            str(tmp_path / "contracts"),
            "--suite",
            str(tmp_path / "suites" / "starter.suite.yaml"),
        ]
    )
    assert code == 0
    contracts = list((tmp_path / "contracts").glob("*.yaml"))
    assert contracts
    suite = (tmp_path / "suites" / "starter.suite.yaml").read_text(encoding="utf-8")
    assert "runtimeai.suite/v1" in suite
    assert contracts[0].name in suite or any(c.stem in suite for c in contracts)
    man2 = json.loads((drafts / "draft_manifest.json").read_text(encoding="utf-8"))
    row = next(d for d in man2["drafts"] if d["id"] == first["id"])
    assert row["status"] == "accepted"


def test_cli_draft_json(tmp_path: Path, capsys):
    code = main(
        [
            "draft",
            str(SAMPLE),
            "--write-drafts",
            str(tmp_path / "out"),
            "--force",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["drafts"]
    assert payload["files_scanned"] >= 3
    ids = [d["id"] for d in payload["drafts"]]
    for lib in LIBRARY_IDS:
        assert lib not in " ".join(ids)


def test_cli_draft_list_and_skip(tmp_path: Path, capsys):
    drafts = tmp_path / "d"
    analyze_and_draft(SAMPLE, write_dir=drafts, force=True)
    man = json.loads((drafts / "draft_manifest.json").read_text(encoding="utf-8"))
    did = man["drafts"][0]["id"]
    assert main(["draft", "list", "--write-drafts", str(drafts)]) == 0
    out = capsys.readouterr().out
    assert did in out
    assert main(["draft", "skip", did, "--write-drafts", str(drafts)]) == 0
    man2 = json.loads((drafts / "draft_manifest.json").read_text(encoding="utf-8"))
    assert next(d for d in man2["drafts"] if d["id"] == did)["status"] == "skipped"


def test_concatenated_system_const_is_stitched(tmp_path: Path):
    app = tmp_path / "tutor"
    (app / "js").mkdir(parents=True)
    (app / "js" / "homework-intake.js").write_text(
        "import Anthropic from '@anthropic-ai/sdk';\n"
        "function build() {\n"
        "  const TAMMY_SYSTEM =\n"
        "    'You help a parent prepare homework.\\n' +\n"
        "    'Return JSON only. Never give final answers.\\n' +\n"
        "    'Memory aids = one core rule + when to use.';\n"
        "  client.messages.create({ system: TAMMY_SYSTEM });\n"
        "}\n",
        encoding="utf-8",
    )
    scan = scan_repo(app)
    bodies = [s.value for s in scan.strings]
    blob = "\n".join(bodies)
    assert any(s.name == "TAMMY_SYSTEM" for s in scan.strings)
    assert "Never give final answers" in blob
    assert "Memory aids" in blob
    props = propose_paths(scan)
    assert any("never give final answers" in p.system.lower() for p in props)


def test_propose_does_not_use_library_id_when_sql_filename(tmp_path: Path):
    app = tmp_path / "app"
    (app / "src").mkdir(parents=True)
    (app / "src" / "generate.ts").write_text(
        'export const SYSTEM = "Retain the student essay. Use [PLANNER:ADD] tokens.";\n'
        "import OpenAI from 'openai';\n"
        "client.chat.completions.create({ model: process.env.OPENAI_MODEL });\n",
        encoding="utf-8",
    )
    scan = scan_repo(app)
    props = propose_paths(scan)
    blob = " ".join(p.id for p in props)
    assert "de_sql_optimization_v1" not in blob
    assert "healthcare_prior_auth_v1" not in blob
    assert props
    written = write_drafts(props, tmp_path / "out", force=True)
    assert written["drafts"]
