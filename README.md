# vantage-core

Standalone RuntimeAI check-ride CLI. Author local contracts (or a **suite** of
3–5 paths), run against OpenRouter, get a portable **`runtimeai.decision/v1`**
artifact — with optional **SHA/PR bind** — **no monorepo `server/` required**.

**Seat:** the **decision engine** for ship / stay live on paths you author — not a better
Opik / Braintrust / LangSmith experiment or trace UI. Ingest from their telemetry/exports
(`ingest` → path plans + optional drafts); plug into CI; return clarity on the decision.

**Version:** 0.1.6 — richer `ingest` (extract → prior detectors → drafts) · 0.1.5 still-trust
ritual (`suite rerun --baseline`, `--reps`/`--pass-k`, pass/review/block) · ledger / demo /
suite / bind from 0.1.2–0.1.4.

Partner authoring: [CI · your suite](https://www.vantageai.cc/runtimeai/method/cicd#rai-cicd-custom-fixtures)

## Install

```bash
pip install vantage-core
```

If your shell says `pip: command not found` (common on macOS):

```bash
python3 -m pip install -U vantage-core
```

Or use a venv: `python3 -m venv .venv && source .venv/bin/activate && pip install vantage-core`.

[PyPI](https://pypi.org/project/vantage-core/) · contributors: `pip install -e ./vantage-core` from a clone.

Requires `OPENROUTER_API_KEY` (BYOK). Live runs fail loudly without it.

## Stranger path (under 30 min)

**A — Live demo (sample contracts, no editing)**

```bash
export OPENROUTER_API_KEY=sk-or-...
vantage-core demo --json --save decisions/
vantage-core decisions show decisions/<latest>.json
echo $?
```

Runs the bundled **Acme** 3-path sample suite (refuse · cite · escalate) and writes a dated
decision under `decisions/`. Browse: [`examples/samples/`](examples/samples/) · also shipped inside the package.

**Before / after talk track** (no live run): [`examples/decisions/`](examples/decisions/) —

```bash
vantage-core decisions show examples/decisions/before_pass.json
vantage-core decisions show examples/decisions/after_fail.json
```

**B — Scaffold your own (partner authors — we don’t write your suite)**

```bash
vantage-core init
# → samples/     known-good demo pack (run as-is)
# → contracts/   editable starters + TEMPLATE — make these yours
# → suites/starter.suite.yaml
# → decisions/  README.md  .gitignore
```

**C — Edit one path, validate, run your suite**

```bash
# edit contracts/01_refuse_pii.yaml  (id / system / opening / checks)
vantage-core validate ./contracts/01_refuse_pii.yaml
vantage-core suite validate ./suites/starter.suite.yaml
vantage-core suite run ./suites/starter.suite.yaml --json --save decisions/
vantage-core decisions list
echo $?   # 0 iff suite pass_gate.passed
```

**D — Single contract (still supported)**

```bash
vantage-core run --contract ./contracts/01_refuse_pii.yaml --json --save decisions/
```

**E — Library scenario (60s, not your suite)**

```bash
vantage-core run --scenario support_escalation_v1 \
  --model openai/gpt-4o-mini --turns 4 --fail-under 7.0 --json
```

Optional guided draft: `vantage-core init --guided`

## Suite (`runtimeai.suite/v1`)

One decision surface over 3–5 critical paths:

```yaml
schema: runtimeai.suite/v1
id: team.release_paths_v1
name: "Release critical paths"
fail_policy: all_must_pass   # default: any path fail → suite fail
# fail_policy: threshold
# min_passed: 2
# cost_ceiling_usd: 0.50
paths:
  - ../contracts/01_refuse_pii.yaml
  - ../contracts/02_cite_sources.yaml
  - ../contracts/03_escalate_not_guess.yaml
```

```bash
vantage-core suite validate suites/starter.suite.yaml
vantage-core suite run suites/starter.suite.yaml --json --save decisions/
```

Exit **0** iff suite `pass_gate.passed`. JSON includes `suite.paths[]` summaries and
optional nested `path_decisions`. Example: [`examples/suites/`](examples/suites/).

### Dated-change ritual (`suite rerun --baseline`)

Still-trust: after a model/prompt/policy change, re-run and compare to a prior decision.

```bash
# 1) Baseline (before the change)
vantage-core suite run suites/starter.suite.yaml --json --save decisions/
# note the saved path, e.g. decisions/2026-08-01T1500Z_team.release_paths_v1.json

# 2) Change lands → still-trust re-run
vantage-core suite rerun suites/starter.suite.yaml \
  --baseline decisions/<prior>.json \
  --json --save decisions/
echo $?   # current gate only (not “same as baseline”)
```

The new decision has a fresh `session_id` / `generated_at`. With `--baseline`, JSON includes
`compare_to_baseline` (score/cost deltas, path regressions, `gate_transition`).
Exit code always reflects the **current** suite gate.

### N-run (`--reps` / `--pass-k`)

Default remains **single-run**. For release diligence:

```bash
vantage-core suite run suites/starter.suite.yaml --reps 3 --pass-k 2 --json
```

Suite passes when at least K of N full suite runs pass. JSON includes `reps` summaries.
**Cost:** BYOK inference scales roughly ×N.

### Three-state route (`pass` / `review` / `block`)

Every decision `pass_gate.route` is one of:

| route | meaning | exit |
|-------|---------|------|
| `pass` | clear to ship | **0** |
| `review` | near bar / low trust / partial N-run — human look | **2** |
| `block` | do not ship | **1** |

CI tip: treat nonzero as fail (`if [ $? -ne 0 ]`), or special-case `2` for review workflows.
Binary “passed” on the decision remains the scorecard truth; exit follows `route`.

## Dated decisions ledger (free)

Keep dated JSON under `decisions/` — your free “what did we decide then?” ledger.
Filenames: `YYYY-MM-DDTHHMMZ_<suite-or-contract-id>.json`.

```bash
vantage-core demo --json --save decisions/          # or: suite run … --save decisions/
vantage-core decisions list [dir]                   # default: ./decisions
vantage-core decisions show decisions/<file>.json   # human view: score, cost, bind, paths
```

This is **not** hosted / multi-tenant history (paid later). Local files + `bind` are enough for demos and CI artifacts.

## SHA / PR bind

On every `run` / `suite run`, when a SHA is known, the decision includes:

```json
"bind": {
  "git_sha": "…",
  "git_ref": "refs/pull/142/merge",
  "pr_number": 142,
  "source": "github_actions",
  "headline": "PR #142 / SHA abc1234 decided at 2026-08-05T20:00:00Z"
}
```

Resolution order: `VANTAGE_GIT_SHA` → `GITHUB_SHA` → `CI_COMMIT_SHA` → `git rev-parse HEAD`.
PR number from `GITHUB_REF` (`refs/pull/N/…`), `VANTAGE_PR_NUMBER`, or `GITHUB_EVENT_PATH`.

Bind fields are included in `integrity.payload_sha256`.

CI stub (mark as **required** check): [`examples/ci/github-actions-suite-gate.yml`](examples/ci/github-actions-suite-gate.yml)

## Contract format (`runtimeai.contract/v1`)

**Mode B — custom** (your scenarios — preferred):

```yaml
schema: runtimeai.contract/v1
id: my_team.policy_refuse_v1
mode: custom
agent:
  system: |
    You are a policy agent…
  opening: |
    User: …
scorer:
  kind: hard_checks
  checks:
    - id: refuses
      any_of: ["cannot", "refuse"]
      points: 5
```

**Mode A — library replay** (our demos):

```yaml
schema: runtimeai.contract/v1
id: my_team.support_path_v1
mode: library_replay
fail_under: 7.0
turns: 4
library:
  scenario_id: support_escalation_v1
```

See `examples/contracts/starters/` and `examples/contracts/demos/`.

| Starter | Quiet-miss |
|---------|------------|
| `01_refuse_pii.yaml` | Leaks prohibited data |
| `02_cite_sources.yaml` | Invents facts |
| `03_escalate_not_guess.yaml` | Fakes root cause |
| `04_sql_safety.yaml` | Destructive / over-broad SQL |
| `05_routing.yaml` | Wrong queue / fake refund |
| `TEMPLATE.yaml` | Blank |

## Decision artifact

```bash
vantage-core schema
vantage-core validate scorecard.json
```

| Block | Contents |
|-------|----------|
| `contract` | scenario / suite id + content SHA, model, turns, fail_under |
| `scorecard` | score `/10`, rubric, **`pass_gate`** |
| `suite` | (suite run) per-path results + fail_policy |
| `bind` | (when SHA known) git SHA / PR / headline |
| `usd` | `est_eval` |
| `exit` | `0` iff `pass_gate.passed` |
| `integrity` | SHA-256 of the payload (includes bind + suite) |

## Bundled library

| Id | What |
|----|------|
| `support_escalation_v1` | Escalating customer ticket (empty export) → multi-turn + heuristic rubric |
| `de_sql_optimization_v1` | Slow Snowflake query → rewrite + heuristic rubric |

## Publish (maintainers)

**Preferred — GitHub trusted publishing**

1. On PyPI: create project `vantage-core` (or claim name) → **Publishing** → GitHub  
   - Repository: this monorepo  
   - Workflow: `publish-vantage-core.yml`  
   - Environment: `pypi` (match the Actions environment)
2. Bump `version` in `pyproject.toml`
3. Tag and release:

```bash
git tag vantage-core-v0.1.6
git push origin vantage-core-v0.1.6
# Create a GitHub Release for that tag → workflow publishes
```

Or **Actions → Publish vantage-core to PyPI → Run workflow** with `confirm=publish`.

**Manual / token fallback**

```bash
cd vantage-core
./scripts/publish-pypi.sh --check   # build + twine check only
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-…
./scripts/publish-pypi.sh
```

## Complement intake (`ingest`)

Feed a **file export** (LangSmith-shaped JSON). Pipeline: extract evidence → match
**Vantage risk priors** (detectors on user/assistant/error/tags, not a keyword bag) →
rank by severity × failure shape → optional **contract drafts** with openings from
*their* turns. Not a trace UI. Not OAuth. Partner still owns the suite.

```bash
vantage-core ingest examples/ingest/langsmith_export_sample.json
vantage-core ingest examples/ingest/langsmith_export_sample.json \
  --write-drafts ./contracts_drafts --force
```

Then edit drafts → `suite run` / `suite rerun --baseline`.
**Claim:** export/manual complement; drafts are suggestions until they own them.

## Changelog (0.1.6)

- **Richer ingest** — extract → prior detectors → confidence/severity/approach → `--write-drafts`
- Client-custom openings from export turns + Vantage approach priors per risk family

## Changelog (0.1.5)

- **`suite rerun --baseline`** — still-trust re-run; fresh decision id/timestamp
- **`compare_to_baseline`** on the new decision (score/cost deltas, path regressions, gate transition)
- Exit code = **current** suite gate (not “matched baseline”)
- **`ingest --suggest-paths`** — LangSmith-shaped export → path suggestions (complement, not OAuth)
- **N-run** — `suite run|rerun --reps N --pass-k K` (default single-run)
- **Three-state route** — `pass_gate.route`: `pass`|`review`|`block` · exit 0/2/1

## Changelog (0.1.4)

- **Dated decisions ledger** — `decisions list` / `decisions show`; `--save DIR` on `demo` / `suite run` / `run`
- **Fixtures** — `examples/decisions/before_pass.json` + `after_fail.json` (same suite id, different bind / gate)

## Changelog (0.1.3)

- **Sample pack** (`samples/`) — Acme 3-path demo suite + optional SQL/routing
- **`vantage-core demo`** — run samples with no init
- **`init`** also copies `samples/` alongside editable `contracts/`

## Changelog (0.1.2)

- **`runtimeai.suite/v1`** + `vantage-core suite validate|run`
- **SHA/PR bind** on decision artifacts (`bind` block)
- **`init`** scaffolds contracts + starter suite + `decisions/` + README
- Starters: SQL safety + routing templates

## Dev monorepo parity

```bash
VANTAGE_USE_MONOREPO=1 vantage-core run --scenario support_escalation_v1 …
# or: vantage-core run --monorepo --scenario …
```

## Related

- Product page: https://www.vantageai.cc/runtimeai/method/cicd
- IDE package: `pip install runtimeai-ide`
- Authoring checklist: `marketing/growth/AUTHORING_CHECKLIST.md`
