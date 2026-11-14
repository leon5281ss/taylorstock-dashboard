#!/usr/bin/env bash
# Safely commit ONLY validated public data from one explicitly allowed directory.
# Rebase onto the most recent main (never force push), retry bounded concurrent
# non-fast-forward conflicts, and fail closed on same-path content collisions.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "::error::usage: bash scripts/safe_commit_public_data.sh <allowed-directory> <commit-message>" >&2
  exit 2
fi

allowed_dir="$1"
message="$2"
case "$allowed_dir" in
  data/market_backfill_pilot|data/market_daily|data/corporate_action_research|data/institutional_research|data/tdcc_weekly_research|data/tdcc_external_history_research) ;;
  *)
    echo "::error::Refusing to stage directory outside the public-data allowlist." >&2
    exit 2
    ;;
esac

if [[ ! -d "$allowed_dir" ]]; then
  echo "Allowed directory contains no new public archives: $allowed_dir"
  exit 0
fi

if ! git diff --cached --quiet; then
  echo "::error::Index was already staged; refusing to mix unrelated files." >&2
  exit 1
fi

git add -- "$allowed_dir"

if git diff --cached --quiet; then
  echo "No changes in verified public archives: $allowed_dir"
  exit 0
fi

# Refuse accidental deletions, scripts, private records or malformed artifacts.
if [[ -n "$(git diff --cached --diff-filter=D --name-only)" ]]; then
  echo "::error::Deletion of a prior archive requires manual review." >&2
  exit 1
fi

while IFS= read -r -d '' path; do
  if [[ "$path" != "$allowed_dir/"* || "$path" != *.json.gz ]]; then
    echo "::error::Unexpected staged file; refusing to publish." >&2
    exit 1
  fi
done < <(git diff --cached --name-only -z)

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git commit -m "$message"

# An unrelated main change while fetching should not discard verified data.
# A same-file conflict is NOT automatically resolved: fail closed for review.
max_attempts=5
for ((attempt=1;attempt<=max_attempts;attempt++)); do
  git fetch --quiet origin main
  if ! git rebase --no-autostash origin/main; then
    echo "::error::Concurrent edits overlap archived files; refusing to overwrite." >&2
    git rebase --abort || true
    exit 1
  fi
  if [[ "$(git rev-list --count origin/main..HEAD)" == "0" ]]; then
    echo "Identical public archive commit was already integrated."
    exit 0
  fi
  if git push origin HEAD:main; then
    echo "Committed validated public archives after safe main sync."
    exit 0
  fi
  echo "::warning::Concurrent main update detected (attempt $attempt/$max_attempts); refreshing."
  sleep "$((attempt * 2))"
done

echo "::error::Exhausted safe retries; public archive remains unpushed. No force push attempted." >&2
exit 1
