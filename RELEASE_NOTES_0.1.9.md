# vantage-core 0.1.9

**Tag:** `vantage-core-v0.1.9`

Try the CLI with no RuntimeAI account and no API key. You get a saved decision file and an HTML scorecard you can open in a browser.

## Try this

```bash
python3 -m pip install --no-cache-dir -U vantage-core
vantage-core --version   # 0.1.9
vantage-core demo --save decisions/
vantage-core report "$(vantage-core decisions latest)" --html decisions/suite.html
```

Open `decisions/suite.html`. That is the memo.

## What changed

- **Saving the demo now writes files.** In 0.1.8, `demo --save` printed a walkthrough and left the folder empty, so the next command had nothing to open.
- **A correct short answer can pass.** Live `demo --live` (needs an OpenRouter key) no longer fails just because the model’s reply is brief. Empty replies still fail.

## What this is not

Not a Cloud dashboard. The HTML file stays on your machine — or in **your** GitHub Actions / GitLab artifacts if you wire CI. Hosted history remains paid.
