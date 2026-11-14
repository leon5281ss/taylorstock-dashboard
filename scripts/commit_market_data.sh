#!/usr/bin/env bash
# Persist public GitHub Actions archives without force pushing across competing jobs.
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: commit_market_data.sh <allowed-public-directory> <commit-message>" >&2
  exit 2
fi

directory="$1"
message="$2"
case "$directory" in
  data/market_daily|data/market_backfill_pilot|data/corporate_action_research) ;;
  *)
    echo "Refusing to stage a non-allowlisted directory: $directory" >&2
    exit 2 ;;
esac

git add -- "$directory"
if git diff --cached --quiet; then
  echo "No new verified archives in $directory; nothing to publish."
  exit 0
fi

# Guard against accidental inclusion of secrets or unrelated staged files.
while IFS= read -r path; do
  case "$path" in
    "$directory"/*) ;;
    *)
      echo "Refusing unrelated staged file: $path" >&2
      exit 2 ;;
  esac
done < <(git diff --cached --name-only)

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git commit -m "$message"

# Other pipelines may update main while this job is collecting official data.
# Fetch/rebase without force pushes; a conflict is a hard stop for review.
for attempt in 1 2 3 4; do
  if git push origin HEAD:main; then
    echo "Verified public archives committed, attempt $attempt."
    exit 0
  fi
  if [ "$attempt" -eq 4 ]; then
    echo "GitHub main advanced repeatedly; safely stopped without force push." >&2
    exit 1
  fi
  echo "GitHub main advanced during archive, syncing and retrying ($attempt/3)."
  git fetch origin main
  if ! git rebase origin/main; then
    git rebase --abort || true
    echo "Data archive rebase conflict; no overwrite or force push attempted." >&2
    exit 1
  fi
  sleep 2
done
