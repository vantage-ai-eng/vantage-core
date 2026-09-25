# vantage-core 0.1.20

**Tag:** `vantage-core-v0.1.20` · **PyPI:** pending

Two fixes and a listing. The gate is now installable as a GitHub Action, and it runs
on every Python version this package claims to support — which, until this release,
it did not.

```bash
vantage-core --version   # 0.1.20
```

## Ship-gate GitHub Action

```yaml
- uses: vantage-ai-eng/vantage-core@v1
  with:
    suite: suites/starter.suite.yaml
    openrouter-api-key: ${{ secrets.OPENROUTER_API_KEY }}
```

Four lines in place of the ~90-line workflow `vantage-core ci stub github` emits. The
action sets up Python, installs the CLI, validates the suite, restores the last
successful decision recorded on your default branch, re-decides against it, builds the
scorecard memo and Center, uploads the decision artifact, and posts the verdict as a PR
comment.

Exit codes are unchanged: **0** pass · **2** review · **1** block. `fail-on` defaults to
`block`, so a `review` verdict reports without breaking the build. Set `fail-on: review`
to gate on both, or `fail-on: never` while you tune a suite. If the decide step cannot
produce an exit code, the gate fails closed.

Inputs and outputs are documented in [`action.yml`](action.yml). The `ci stub` command
still emits a plain workflow for anyone who would rather own it.

## Fixed — `center` and `report` were broken on Python 3.10 and 3.11

`pyproject.toml` declared `requires-python = ">=3.10"` and carried PyPI classifiers for
3.10, 3.11 and 3.12. But `vantage_core/center.py` and `vantage_core/report.py` contained
PEP 701 f-string syntax, which only parses on 3.12 and later. Neither module compiled on
3.10.

Both load lazily, so `import vantage_core` succeeded and nothing surfaced until you ran
`vantage-core center` or `vantage-core report` — at which point you got a `SyntaxError`
on a Python version this package advertised.

Seven lines hoisted out of f-string expressions. The emitted HTML is byte-identical.
Full test suite on Python 3.10: **220 passed**, previously 8 failed plus a collection
error.

If you are on 3.10 or 3.11 and the scorecard or Control Center never worked for you,
this is why. Upgrade to 0.1.20.

## Fixed — a test that passed because its input was missing

`test_scan_skips_node_modules_and_env` asserts that `.env` does not appear in the paths
`scan_repo` collects — the check that a draft scan cannot pull secrets out of a repo.
`.env` is gitignored, so in any fresh clone the file was absent and the assertion passed
on absence rather than on the scanner skipping it. The fixture is now written at run
time, and paths are compared relative to the scan root.

Worth stating plainly, since this package exists to catch exactly this: a green test that
tests nothing is the failure mode, not the exception.
