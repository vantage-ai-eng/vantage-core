# Sample contracts — start here

## Fastest paths

### A — Live demo (no editing)

```bash
export OPENROUTER_API_KEY=sk-or-...
pip install vantage-core
vantage-core demo --json
echo $?
```

Runs the bundled **Acme Support Agent** suite (refuse · cite · escalate).  
Same files: [`../samples/`](../samples/) · also `vantage-core/vantage_core/samples/` in the package.

### B — Starting point for your paths

```bash
vantage-core init
# → samples/     known-good demo pack (run as-is)
# → contracts/   editable copies — make these YOURS
# → suites/starter.suite.yaml
# → decisions/

# Edit contracts/01_refuse_pii.yaml, then:
vantage-core suite run suites/starter.suite.yaml --json
```

Site: https://www.vantageai.cc/runtimeai/method/cicd#rai-cicd-custom-fixtures

## Samples (demo + copy)

| File | Quiet-miss |
|------|------------|
| [`../samples/01_refuse_pii.yaml`](../samples/01_refuse_pii.yaml) | Leaks / dumps prohibited data |
| [`../samples/02_cite_sources.yaml`](../samples/02_cite_sources.yaml) | Invents facts with no cite |
| [`../samples/03_escalate_not_guess.yaml`](../samples/03_escalate_not_guess.yaml) | Guesses root cause instead of escalating |
| [`../samples/04_sql_safety.yaml`](../samples/04_sql_safety.yaml) | Destructive / over-broad SQL |
| [`../samples/05_routing.yaml`](../samples/05_routing.yaml) | Wrong queue / fake refund |
| [`../samples/demo.suite.yaml`](../samples/demo.suite.yaml) | 3-path Acme suite |

### Starters (Mode B — what `init` copies into `contracts/`)

| File | Quiet-miss it catches |
|------|------------------------|
| [`starters/01_refuse_pii.yaml`](starters/01_refuse_pii.yaml) | Leaks / dumps prohibited data |
| [`starters/02_cite_sources.yaml`](starters/02_cite_sources.yaml) | Invents facts with no cite |
| [`starters/03_escalate_not_guess.yaml`](starters/03_escalate_not_guess.yaml) | Guesses root cause instead of escalating |
| [`starters/04_sql_safety.yaml`](starters/04_sql_safety.yaml) | Destructive / over-broad SQL |
| [`starters/05_routing.yaml`](starters/05_routing.yaml) | Wrong queue / fake refund |
| [`starters/TEMPLATE.yaml`](starters/TEMPLATE.yaml) | Blank — fill in your path |

Same files ship inside the package (`vantage-core init`).  
CI bind stub: [`../ci/github-actions-suite-gate.yml`](../ci/github-actions-suite-gate.yml)  
Partner checklist: [`marketing/growth/AUTHORING_CHECKLIST.md`](../../../marketing/growth/AUTHORING_CHECKLIST.md)

## Demos only (Mode A — our library)

```bash
vantage-core run --scenario support_escalation_v1 --turns 4 --fail-under 7.0
# or: --contract demos/support_escalation.yaml
```

| File | Bundled id |
|------|------------|
| [`demos/support_escalation.yaml`](demos/support_escalation.yaml) | `support_escalation_v1` |
| [`demos/sql_library_replay.yaml`](demos/sql_library_replay.yaml) | `de_sql_optimization_v1` |

Library demos prove the gate. **Your** release control: `samples/` → copy → `contracts/` → your suite.
