# vantage-core

Standalone RuntimeAI still-trust CLI. Author local contracts (or a **suite** of
3–5 critical paths), run against OpenRouter, get a portable **`runtimeai.decision/v1`**
artifact — with optional **SHA/PR bind** — **no monorepo `server/` required**.

**Seat:** the free **CI still-trust gate** for the ship decision on paths you author —
go/no-go across functionality, cost, reliability, safety, and compliance — not a better
Opik / Braintrust / LangSmith experiment or trace UI. Observability inspects; Vantage decides.
Ingest from their telemetry/exports (`ingest` → path plans + optional drafts); plug into CI;
return the verdict.

**Version:** 0.1.16 — DEMO chrome for design partners · 0.1.15 demo in wheel · 0.1.14 Coverage · 0.1.13 Center + fleet

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

Requires `OPENROUTER_API_KEY` (BYOK) for live model runs. Live runs fail loudly without it.
`vantage-core attest` is separate: it needs `RUNTIMEAI_API_KEY` (a RuntimeAI Cloud key). Verify needs neither.

## Stranger path (under 30 min)

**A — Interactive Control Center (no API key — recommended)**

```bash
pip install vantage-core
vantage-core demo --interactive
# same: vantage-core center --demo
# → http://127.0.0.1:8767/  · beats 1–7 · Center panel refreshes after each beat
```

Bundled with the package: fixtures, sample Obs exports, fleet sim, report samples. No clone required.

**Offline CLI talk track (no browser)**

```bash
vantage-core demo --save decisions/
vantage-core report "$(vantage-core decisions latest)" --html decisions/suite.html
vantage-core center --decisions decisions/ --html decisions/center.html
# open decisions/center.html — Control Center (management); suite.html is the scorecard memo
# no RuntimeAI account
```

Offline CLI talk track (no key) prints the silent-miss SAY lines **and Coverage** (Live / Seen ungated from a sample LangSmith export):

```bash
vantage-core demo --offline
```

`--save` writes before/after JSON, sample ingest plan, and `center.html` with Coverage even without an API key.
Needs a key only for a live model run: `vantage-core demo --live`.

Clone of this repo also has the same fixtures under [`examples/decisions/`](examples/decisions/).

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
echo $?   # 0 iff suite pass_gate.passed
vantage-core decisions list
vantage-core report "$(vantage-core decisions latest)" --html decisions/suite.html
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

# 2) Change lands → still-trust re-run vs newest dated decision
vantage-core suite rerun suites/starter.suite.yaml \
  --baseline latest \
  --json --save decisions/
echo $?   # current gate only (not “same as baseline”)
# or: --baseline decisions/<prior>.json   ·   --baseline decisions/
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
vantage-core decisions latest                       # path of newest JSON (scripts / --baseline latest)
vantage-core decisions show decisions/<file>.json   # human view: score, cost, bind, paths
```

This is **not** hosted / multi-tenant history (not built). Local files + `bind` are enough for demos and CI artifacts.

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

On GitHub Actions / GitLab CI, `--ci-comment` posts bind + `compare_to_baseline` on the PR/MR
(one living comment, updated in place). Token from `GITHUB_TOKEN` / `CI_JOB_TOKEN` — no GitHub App.

```bash
vantage-core ci stub github    # .github/workflows/vantage-core-suite-gate.yml
vantage-core ci stub gitlab    # .gitlab-ci.vantage-core.yml
# or: vantage-core init --ci
```

CI stubs (mark as **required** check): [`examples/ci/`](examples/ci/) — PRs **re-decide vs last ship**, they do not one-shot `suite run`. Stubs upload **JSON + HTML + PDF** as `runtimeai-decision` (their artifact store — not a RuntimeAI Cloud dashboard).

## Human scorecard from CI

Same axes / pass-review-block / bind / compare-to-baseline as the Simulator memo — offline, no RuntimeAI account:

```bash
vantage-core report decisions/suite.json --html decisions/suite.html
vantage-core report decisions/suite.json --pdf decisions/suite.pdf    # optional; no extra deps
```

Open the HTML in a browser (or the PDF). Footer states **local artifact — not RuntimeAI Cloud history**. Hosted multi-owner history is not built.

## RuntimeAI Control Center (management lens)

**See it (no key):** `vantage-core demo --interactive` or `vantage-core center --demo` → browser at `:8767`.

One local HTML surface for suite · bar · last motion · path blockers · bind — not N scripts, not a hosted dashboard:

```bash
# Single suite (deep cockpit) — what CI uses for the gated suite
vantage-core center --suite suites/starter.suite.yaml --decisions decisions/ --html decisions/center.html

# Fleet rollup — discovers suites/*.suite.yaml; advisory register + focused suite detail
vantage-core center --decisions decisions/ --html decisions/center.html
# optional: --ingest export-analysis.json   (or auto-pick decisions/ingest-*.json)
# optional: --open
```

`suite run` / `suite rerun --save decisions/` also refreshes `decisions/center.html` automatically. CI stubs re-run `center` with `if: always()` so a blocked gate still leaves a readable cockpit.

**Across suites:** each suite keeps its own bar and CI exit (`0/2/1`). The fleet register is advisory (e.g. `2 CLEAR · 1 STOP`) — not a fleet gate. Chain scope remains account + `suite_id`.

**Stranger path (red CI):** download the `runtimeai-decision` artifact → open `center.html` → fix what the path register shows → push and let CI re-decide. Details: [`examples/ci/README.md`](examples/ci/README.md#stranger-path--after-a-red-check).

```bash
# After any saved decision (dated file or the CI tee'd suite.json)
vantage-core decisions latest                    # path of newest JSON
vantage-core report "$(vantage-core decisions latest)" --html decisions/suite.html
vantage-core center --decisions decisions/ --html decisions/center.html
```

GitHub Actions / GitLab stubs already run `report` + `center` with `if: always()` / `after_script` so a blocked gate still leaves a readable memo and Center. Report/Center failure does not change the suite exit code.

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
| `trigger` | (optional) `change` · `cadence` · `catalog` — why this decision fired |
| `usd` | `est_eval` |
| `exit` | `0` iff `pass_gate.passed` |
| `integrity` | SHA-256 of the payload (includes bind + suite) |

Detached countersignature (**verify is live**, offline and free; **attest is live** on production):

```bash
# after demo --save or suite run --save (dated file, not suite.json)
export RUNTIMEAI_API_KEY=rai_live_…          # issuance (free in preview); not OPENROUTER_API_KEY
vantage-core attest "$(vantage-core decisions latest)"
vantage-core verify "$(vantage-core decisions latest)"   # sibling *.attestation.json; no network
```

Default verify uses the keyring shipped in this package — no network. Design note: [`docs/ATTESTATION.md`](docs/ATTESTATION.md). Canonical published keys: https://www.vantageai.cc/runtimeai/attestation/keys.json

CLI `attest` POSTs digest-only when `RUNTIMEAI_API_KEY` is set. Missing key fails cleanly (no POST). A server `501` maps to a clean message — never a raw 501 body. Verify remains free and offline.

Cadence re-decide (`suite rerun --trigger cadence`) is the catch for silent same-id change. Catalog ID add/retire can accelerate it; it does not observe silent drift. [`docs/CADENCE.md`](docs/CADENCE.md).

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
git tag vantage-core-v0.1.11
git push origin vantage-core-v0.1.11
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

Already on **LangSmith**, **Braintrust**, or similar? Export a JSON dump → one CLI command →
ranked path suggestions + optional draft contracts.

**Accelerate authoring** = shorter blank-page work (ranked paths + optional drafts from *their*
turns + Vantage priors). Someone still edits system prompts, hard-checks, IDs, and owns the suite.
**Auto-write** would mean export in → production suite out with no human ownership — we do **not**
do that. No live sync (no OAuth).

| | Accelerate (what we ship) | Auto-write (not us) |
|---|---|---|
| Output | Suggestions + editable drafts | Finished suite that ships as-is |
| Who owns the bar | Partner | Tool |
| Sync | One-shot file import | Live OAuth / continuous sync |

Pipeline: extract evidence → match **Vantage risk priors** (detectors on user/assistant/error/tags,
not a keyword bag) → rank by severity × failure shape → optional **contract drafts** with openings
from *their* turns. Not a trace UI. Partner still owns the suite.

```bash
# LangSmith-shaped (top-level "runs")
vantage-core ingest examples/ingest/langsmith_export_sample.json

# Braintrust-shaped (top-level "events" with input/output)
vantage-core ingest examples/ingest/braintrust_export_sample.json

vantage-core ingest path/to/export.json --write-drafts ./contracts_drafts --force
```

Then edit drafts → `suite run` / `suite rerun --baseline`.
**Claim:** export/manual complement; drafts are suggestions until they own them.
See `examples/ingest/README.md`.
FAQ: https://www.vantageai.cc/runtimeai/faq#rai-faq-accelerate-authoring

## Changelog (0.1.16)

- **Clear DEMO chrome** — interactive walkthrough banner / title / badge so design partners cannot confuse sample fixtures with their CI ledger. Real Control Center HTML still loads in the iframe.

## Changelog (0.1.15)

- **Control Center demo in the wheel** — `pip install vantage-core` then `vantage-core demo --interactive` (or `center --demo`) runs the full browser walkthrough: fixtures, Obs samples, fleet sim, report samples. No monorepo clone. Naming: **RuntimeAI Control Center**.
- **Coverage** (from 0.1.14) — Live / Seen ungated / Pending / Stale on partner exports. `demo --interactive` / `demo --offline` mirror **0.1.16**.

## Changelog (0.1.14)

- **Coverage** — Center reads their existing tools. Ingest a LangSmith / Braintrust export; the cockpit shows **Live** (on last ship-cleared PASS) / **Seen ungated** (in the export, not in the suite) / **Pending** (authored, not yet on that PASS) / **Stale** (on last PASS, absent from recent export). Packaged sample export so `pip install` can demo it. Not monitoring, not OAuth, not a trace UI.

## Changelog (0.1.13)

- **RuntimeAI Control Center** — local control surface (`vantage-core center` / `demo --interactive`). CI is the brake; Control Center is the cockpit: ship / still-trust verdict, what blocks, path register (`why` + `priority:`), bar, bind, vs last ship, motion history, one primary next, author-next ingest panel. Fleet register across `suites/*.suite.yaml` is advisory only. Offline HTML — not a Cloud dashboard. `--save` and CI stubs refresh/upload `center.html`.

## Changelog (0.1.12)

- **Metered cost** — when the provider returns usage, `usd.source` is `metered` and token classes (input, output, cached read, cache write, reasoning) are recorded separately. No usage → `estimated` (`calls × (1500 in + 350 out) ×` the pinned rate table). `config_stamp.model_costs_sha256` still pins the table.
- **Agent-turn latency** — `latency.agent_turn_latency_ms[]` is request→response per agent turn. `elapsed_s` stays wall-clock. `harness_overhead_s` is the rest. `turns_to_closure` is **null** if the scenario never closed — never the turn cap. Gate on `turn_latency_p95_ms`, not the mean.
- **Opt-in ceilings** — path-level `cost_ceiling_usd` and `latency_ceiling_p95_ms` on `runtimeai.contract/v1`; suite-level `latency_ceiling_p95_ms` plus existing `cost_ceiling_usd`. **No defaults.** Absent does not gate. Present breach is `over_cost_ceiling` / `over_latency_ceiling`.
- **Opt-in regression** — suite `latency_regression_pct` / `cost_regression_pct` vs last-ship baseline. No default. Compare always reports p95 and USD deltas.
- **Library scorer identity** — `library:…` contracts bind `scorer_sha256` (module body) into `content_sha256` / the suite bar. A later wheel cannot silently change the heuristic under the same hash.

## Changelog (0.1.11)

- **`verify` recomputes `suite_sha256` from suite content.** **0.1.10's verify does not recompute the suite hash; 0.1.11 does.** A client-supplied stamp cannot fake the bar.
- Live `suite run` stamps suite `fail_under` and per-path `content_sha256` / `bar_sha256` so that recomputation is possible.
- Stamp-vs-envelope fallback is gated on signed `pins.runner_version` **older than 0.1.11**. Missing hashes on a modern runner fail verify.

## Changelog (0.1.10)

- **Decision attestation ships here.** **PyPI 0.1.9 predates attestation and cannot be replaced** (PyPI versions are immutable). Git labeled some attestation work as 0.1.9; that published wheel does not include it. This is 0.1.10.
- **`verify`** — offline, free, no account. Default keyring is shipped in the package (`vantage_core/keys/`). `--keyring PATH|URL` is opt-in for a newer kid.
- **`attest`** — POST digest-only (`RUNTIMEAI_API_KEY`). Never sends the decision body.
- **Published keyring** — in-package copy of https://www.vantageai.cc/runtimeai/attestation/keys.json (`kid` `vantage-attestation-2026-08`).
- **Subject binding** — new envelopes carry an issuer-assigned `subject` (`acct_…` or `runtimeai:master`). Never client-supplied.
- **`suite_sha256`** — suite definition hash on the envelope and on suite-level decisions.
- **`trigger` stamping** — live `run` / `suite run` stamp `trigger.kind` (`change` / `cadence` / `catalog`) inside the integrity hash.
- **`config_stamp.model_costs_sha256`** — populated from the rate table actually used on live runs.

## Changelog (0.1.9)

- **`demo --save`** writes example decision files with no API key (0.1.8 printed the walkthrough and saved nothing)
- Offline demo prints `report --html` so you can open the scorecard next
- Live `demo --live` no longer fails a correct short answer just because it is brief

## Changelog (0.1.8)

- **`vantage-core report <decision.json> --html`** — self-contained scorecard memo from `runtimeai.decision/v1` (offline; no account)
- Optional **`--pdf`** (no extra deps) for a printable CI artifact
- GitHub / GitLab stubs upload **JSON + HTML + PDF** as `runtimeai-decision` (their CI store — not a free Cloud dashboard)
- Report generation is best-effort (`if: always()` / `|| true`); gate exit stays from `suite run`

## Changelog (0.1.7)

- **Still-trust CI** — GitHub Actions + GitLab stubs re-decide vs last ship (`suite rerun --baseline`)
- **`--baseline latest`** (or a directory) — newest `runtimeai.decision/v1` in `decisions/`
- **`decisions latest`** — print that path for scripts
- **`--ci-comment`** — post bind headline + compare on the GitHub PR / GitLab MR
- **`vantage-core ci stub github|gitlab`** · `init --ci`
- **`vantage-core demo`** — 60s talk track with no API key; `--live` for the sample suite

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
- Authoring checklist: https://www.vantageai.cc/runtimeai/method/cicd#rai-cicd-custom-fixtures
