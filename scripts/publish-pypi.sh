#!/usr/bin/env bash
# Build and publish vantage-core to PyPI (local/manual path).
# Prefer GitHub Actions trusted publishing via tag vantage-core-vX.Y.Z
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Prefer repo venv if present (avoids system Python PATH issues).
REPO_ROOT="$(cd "$ROOT/.." && pwd)"
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PY="$REPO_ROOT/.venv/bin/python"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="${PYTHON:-python3}"
fi

echo "Using: $PY"

"$PY" -m pip install -U pip build twine pytest >/dev/null
"$PY" -m pip install -e ".[dev]" -q
rm -rf dist build ./*.egg-info vantage_core.egg-info
"$PY" -m pytest -q
"$PY" -m build
"$PY" -m twine check dist/*

if [[ "${1:-}" == "--check" ]]; then
  echo "Build OK. Artifacts in dist/ (not uploaded)."
  ls -la dist/
  exit 0
fi

: "${TWINE_USERNAME:=__token__}"
if [[ -z "${TWINE_PASSWORD:-}" ]]; then
  echo "Set TWINE_PASSWORD to a PyPI API token (or use GH Actions trusted publishing)." >&2
  echo "  export TWINE_USERNAME=__token__" >&2
  echo "  export TWINE_PASSWORD=pypi-…" >&2
  exit 2
fi

"$PY" -m twine upload dist/*
echo "Published. Verify: https://pypi.org/project/vantage-core/"
echo "Then: python3 -m pip index versions vantage-core"
