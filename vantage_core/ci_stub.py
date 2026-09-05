"""Still-trust CI stubs — GitHub Actions + GitLab CI.

Write with: vantage-core ci stub github|gitlab
Not a GitHub App. Partner marks the job as a required check.
Human memo (HTML/PDF) + Control Center are CI artifacts in *their* store —
not a Cloud dashboard.
"""

from __future__ import annotations

from pathlib import Path

GITHUB_DEFAULT = Path(".github/workflows/vantage-core-suite-gate.yml")
GITLAB_DEFAULT = Path(".gitlab-ci.vantage-core.yml")

GITHUB_SUITE_GATE_YAML = """\
# Still-trust suite gate — mark as a required check on the protected branch.
# PR/push: re-decide vs last ship (trigger=change).
# Weekly schedule: cadence re-decide vs last ship (trigger=cadence).
# Bind: GITHUB_SHA / PR → decision.bind
# Comment: bind headline + compare_to_baseline (pull-requests: write)
# Memo: suite.html (+ suite.pdf) + Control Center (center.html) as artifacts — not a Cloud dashboard.
#
# Requires vantage-core 0.1.16  ·  secret: OPENROUTER_API_KEY
# First PR after a green default-branch run is when --baseline appears.
# Cadence does not observe silent same-id drift; it re-decides.
name: vantage-core suite gate

on:
  pull_request:
  push:
    branches: [main, master]
  schedule:
    - cron: "0 6 * * 1"

permissions:
  contents: read
  actions: read
  pull-requests: write

jobs:
  suite-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install vantage-core
        run: pip install -U 'vantage-core>=0.1.8'

      - name: Validate suite
        run: vantage-core suite validate suites/starter.suite.yaml

      - name: Restore last ship decision
        if: github.event_name != 'push'
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          mkdir -p baseline
          DEFAULT_BRANCH="${{ github.event.repository.default_branch }}"
          RID=$(gh run list --repo "$GITHUB_REPOSITORY" \\
            --branch "$DEFAULT_BRANCH" \\
            --workflow "${{ github.workflow }}" \\
            --status success --limit 1 \\
            --json databaseId --jq '.[0].databaseId' || true)
          if [ -n "$RID" ] && [ "$RID" != "null" ]; then
            gh run download "$RID" --name runtimeai-decision --dir baseline || true
          fi
          if [ -f baseline/decisions/suite.json ] && [ ! -f baseline/suite.json ]; then
            mv baseline/decisions/suite.json baseline/suite.json
          fi

      - name: Re-decide vs last ship (PR/cadence) or record ship (default branch)
        env:
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
        run: |
          set -euo pipefail
          mkdir -p decisions
          if [ "${{ github.event_name }}" = "schedule" ] && [ -f baseline/suite.json ]; then
            vantage-core suite rerun suites/starter.suite.yaml \\
              --baseline baseline/suite.json --trigger cadence \\
              --json --save decisions/ --ci-comment | tee decisions/suite.json
          elif [ "${{ github.event_name }}" = "pull_request" ] && [ -f baseline/suite.json ]; then
            vantage-core suite rerun suites/starter.suite.yaml \\
              --baseline baseline/suite.json --trigger change \\
              --json --save decisions/ --ci-comment | tee decisions/suite.json
          else
            vantage-core suite run suites/starter.suite.yaml \\
              --trigger change \\
              --json --save decisions/ --ci-comment | tee decisions/suite.json
          fi

      - name: Human scorecard memo + Control Center
        if: always()
        continue-on-error: true
        run: |
          if [ -f decisions/suite.json ]; then
            vantage-core report decisions/suite.json \\
              --html decisions/suite.html \\
              --pdf decisions/suite.pdf
            vantage-core center \\
              --decisions decisions/ \\
              --decision decisions/suite.json \\
              --html decisions/center.html
          fi

      - name: Upload decision artifact
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: runtimeai-decision
          path: |
            decisions/suite.json
            decisions/suite.html
            decisions/suite.pdf
            decisions/center.html
          if-no-files-found: ignore
"""

GITLAB_SUITE_GATE_YAML = """\
# vantage-core still-trust suite gate (0.1.16)
# Include from .gitlab-ci.yml:
#   include:
#     - local: .gitlab-ci.vantage-core.yml
# Or copy into .gitlab-ci.yml if you have no other jobs.
#
# CI/CD variable: OPENROUTER_API_KEY (masked)
# MR/push: re-decide vs last ship (trigger=change).
# Pipeline schedule: cadence re-decide vs last ship (trigger=cadence).
# Bind: CI_COMMIT_SHA → decision.bind (source gitlab_ci)
# Comment: bind + compare_to_baseline via CI_JOB_TOKEN / GITLAB_TOKEN
# Memo: suite.html (+ suite.pdf) + Control Center (center.html) as artifacts — not a Cloud dashboard.

stages:
  - gate

suite-gate:
  image: python:3.12-slim
  stage: gate
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - if: $CI_PIPELINE_SOURCE == "schedule"
  variables:
    PIP_DISABLE_PIP_VERSION_CHECK: "1"
  needs:
    - project: $CI_PROJECT_PATH
      job: suite-gate
      ref: $CI_DEFAULT_BRANCH
      artifacts: true
      optional: true
  before_script:
    - pip install -q -U 'vantage-core>=0.1.8'
    - vantage-core suite validate suites/starter.suite.yaml
  script:
    - mkdir -p baseline decisions
    - |
      if [ -f decisions/suite.json ]; then
        mv decisions/suite.json baseline/suite.json
      fi
    - |
      set -euo pipefail
      if [ "${CI_PIPELINE_SOURCE:-}" = "schedule" ] && [ -f baseline/suite.json ]; then
        vantage-core suite rerun suites/starter.suite.yaml \\
          --baseline baseline/suite.json --trigger cadence \\
          --json --save decisions/ --ci-comment | tee decisions/suite.json
      elif [ -n "${CI_MERGE_REQUEST_IID:-}" ] && [ -f baseline/suite.json ]; then
        vantage-core suite rerun suites/starter.suite.yaml \\
          --baseline baseline/suite.json --trigger change \\
          --json --save decisions/ --ci-comment | tee decisions/suite.json
      else
        vantage-core suite run suites/starter.suite.yaml \\
          --trigger change \\
          --json --save decisions/ --ci-comment | tee decisions/suite.json
      fi
  after_script:
    - |
      if [ -f decisions/suite.json ]; then
        vantage-core report decisions/suite.json \\
          --html decisions/suite.html \\
          --pdf decisions/suite.pdf || true
        vantage-core center \\
          --decisions decisions/ \\
          --decision decisions/suite.json \\
          --html decisions/center.html || true
      fi
  artifacts:
    when: always
    paths:
      - decisions/suite.json
      - decisions/suite.html
      - decisions/suite.pdf
      - decisions/center.html
    expire_in: 30 days
"""


def github_suite_gate_yaml() -> str:
    return GITHUB_SUITE_GATE_YAML


def gitlab_suite_gate_yaml() -> str:
    return GITLAB_SUITE_GATE_YAML


def default_stub_path(kind: str) -> Path:
    if kind == "github":
        return GITHUB_DEFAULT
    if kind == "gitlab":
        return GITLAB_DEFAULT
    raise ValueError(f"unknown CI stub kind: {kind}")


def stub_body(kind: str) -> str:
    if kind == "github":
        return github_suite_gate_yaml()
    if kind == "gitlab":
        return gitlab_suite_gate_yaml()
    raise ValueError(f"unknown CI stub kind: {kind}")


def write_stub(kind: str, dest: str | Path, *, force: bool = False) -> Path:
    path = Path(dest).expanduser().resolve()
    if path.exists() and not force:
        raise FileExistsError(f"refusing to overwrite {path} (pass --force)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stub_body(kind), encoding="utf-8")
    return path
