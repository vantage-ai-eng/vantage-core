# vantage-core 0.1.19

**Tag:** `vantage-core-v0.1.19` · **PyPI:** live 15 September 2026

Authorized custom authoring: they grant inputs → we draft custom Core contracts → they Accept in Control Center → CI in their repo.

```bash
vantage-core --version   # 0.1.19
vantage-core draft . --write-drafts ./contracts_drafts
vantage-core center --serve   # Accept / Skip / Refine

# Optional grant snapshot (API key / PAT on your machine):
vantage-core grant langsmith --project my-proj --out ./exports/ls.json
vantage-core draft . --grant langsmith,github --github-repo owner/name
```

- Scan authorized local repo / tests / ingest export.
- **Grant snapshots** — `grant langsmith|braintrust|github` / `draft --grant` write local files under `.vantage-grant/`. Tokens stay on their machine. Accept still required.
- Emit 3–5 custom `runtimeai.contract/v1` paths from *their* strings — not library IDs.
- Author next: Accept copies `contracts/` + suite. Static `center.html` stays copy-commands.
- `ci stub --suite` / `draft accept --ci` — required check uses the accepted suite. Secret `OPENROUTER_API_KEY` only.
- MCP `runtimeai_draft_suite` emits Core contracts (needs vantage-core; no OpenRouter).

**Auto-write** = no Accept + continuous bar sync. We do not do that.  
**Grant snapshot** ≠ auto-write. Hosted browser OAuth (token with us) is paid-later.