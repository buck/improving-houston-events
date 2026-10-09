#!/usr/bin/env bash
# Daily job: scrape -> build -> commit/push if anything changed -> alert on problems.
set -uo pipefail
export PATH=/run/current-system/sw/bin:/run/wrappers/bin:$PATH
export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/id_ed25519_improving_deploy -o IdentitiesOnly=yes -o BatchMode=yes"
cd "$(dirname "$0")"

alert() { /usr/local/bin/alert "Improving calendar: $*"; }

summary=$(python3 scrape.py)
rc=$?
python3 build.py || { alert "build.py failed"; exit 1; }

errors=$(jq -r '.errors[]?' <<<"$summary" 2>/dev/null)
comments=$(jq -r '.comment_alerts[]?' <<<"$summary" 2>/dev/null)
if [[ $rc -ne 0 || -n $errors ]]; then
  alert "scrape problem: ${errors:-exit $rc}"
fi
if [[ -n $comments ]]; then
  alert "new comment may change the schedule - $comments"
fi

git add -A data docs posts.txt
if ! git diff --cached --quiet; then
  git commit -q -m "Update events $(date +%F)" && git push -q origin main || alert "git push failed"
fi
exit $rc
