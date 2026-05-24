#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f .env.local ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env.local
  set +a
fi

if [[ -z "${TRACKER_USER_AGENT:-}" ]]; then
  echo "Missing TRACKER_USER_AGENT. Add it to .env.local before collecting SEC data." >&2
  exit 1
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "Missing OPENAI_API_KEY. Add it to .env.local so fetched media items are summarized before publishing." >&2
  exit 1
fi

: "${OPENAI_SUMMARY_MODEL:=gpt-5.4-nano}"
: "${AI_SUMMARY_LIMIT:=500}"
export OPENAI_SUMMARY_MODEL AI_SUMMARY_LIMIT

python3 collect.py
python3 -m unittest discover -s tests -v

if git diff --quiet -- data/feed.json; then
  echo "No feed changes to publish."
  exit 0
fi

git add data/feed.json
git commit -m "Update public activity feed"
git push origin main
echo "Published updated feed. GitHub Pages will deploy from the pushed static data."
