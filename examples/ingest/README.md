# Complement intake — telemetry is one input to custom draft

**Obs shows what ran; Center shows which of those behaviors you already gate, which you still owe, and what the next ship would change.**

Primary door: **`vantage-core draft .`** — authorized repo / tests / ingest export → custom `runtimeai.contract/v1` paths → Accept in Control Center.

Optional **grant snapshot** (API key / PAT on their machine — not auto-write):

```bash
vantage-core grant langsmith --project my-proj --out ./exports/ls.json
vantage-core grant github owner/name --out ./.vantage-grant/repo
# or one shot:
vantage-core draft . --grant langsmith,github --github-repo owner/name --langsmith-project my-proj
```

Already have LangSmith, Braintrust, or similar? **Export a JSON dump** and pass it as `--ingest` (or keep `vantage-core ingest` for ranked plans + Coverage). Open Center to **Accept** drafts and see **Live / Seen ungated / Pending**.

**Accelerate authoring** = shorter blank-page work (custom drafts from what you grant). Someone still Accepts, may refine checks, and owns the suite.  
**Coverage** = same file fuels the cockpit: Live (on last ship-cleared PASS), Seen ungated (export not in suite), Pending (authored, not yet on that PASS).  
**Auto-write** = no Accept + continuous bar sync — we do **not** do that. Grant snapshot ≠ auto-write. Hosted browser OAuth is paid-later.

| | Accelerate (what we ship) | Auto-write (not us) |
|---|---|---|
| Output | Custom drafts you Accept | Finished suite that ships as-is |
| Who owns the bar | Partner | Tool |
| Sync | Authorized local paths + one-shot file | Live OAuth / continuous sync |

We:

1. **Scan** the authorized repo (LLM call sites, policy strings, test oracles)
2. Optionally **ingest** a telemetry export (one input — priors are fallback hints)
3. **Draft** 3–5 custom contracts (not library IDs)
4. Partner **Accepts** in Control Center or CLI

Not a LangSmith/Braintrust UI. Not OAuth. Not hosted history. Partner still owns the suite.
FAQ: https://www.vantageai.cc/runtimeai/faq#rai-faq-accelerate-authoring

```bash
# Custom paths from the repo they authorized
vantage-core draft . --write-drafts ./contracts_drafts
vantage-core center --serve   # Accept / Skip / Refine

# Ingest-only (still valid) — LangSmith-shaped (top-level "runs")
vantage-core ingest examples/ingest/langsmith_export_sample.json

# Braintrust-shaped (top-level "events" with input/output)
vantage-core ingest examples/ingest/braintrust_export_sample.json

# Write editable drafts customized from the export
vantage-core ingest path/to/export.json \
  --write-drafts ./contracts_drafts --force

# Machine-readable
vantage-core ingest path/to/export.json --json
```

Then Accept drafts → `suite run` / `suite rerun --baseline`, and open Center:

```bash
vantage-core center --suite suites/starter.suite.yaml \
  --decisions decisions/ --html decisions/center.html
# picks newest decisions/ingest-*.json when present → Coverage + Author next
# static export = copy-commands; `center --serve` runs Accept against this directory
```

| Source | Typical export shape we accept |
|--------|--------------------------------|
| LangSmith | `{ "runs": [ { "inputs", "outputs", "tags", … } ] }` |
| Braintrust | `{ "events": [ { "input", "output", "scores", … } ] }` or a bare list of rows |
| Similar | Any JSON with run-like objects under `runs` / `events` / `rows` / `items` |

**How to get the file:** LangSmith — download / export runs from the project or API. Braintrust — experiment UI export, or API/SDK fetch of experiment events / dataset rows saved as JSON. Drop the file next to your repo and run `draft --ingest` or `ingest`.

**Claim:** authorized local artifacts; drafts are suggestions until the partner Accepts them.
