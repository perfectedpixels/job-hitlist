#!/bin/sh
# One command to refresh the hitlist. Run from anywhere:
#   ~/Dropbox/Documents/applications/jobsearch/daily.sh          # past week
#   ~/Dropbox/Documents/applications/jobsearch/daily.sh r86400   # past 24h
#
# Every step runs even if the one before it failed: a LinkedIn timeout must
# not skip the Jobright harvest, and a Mail hiccup must not skip scoring.
# Order still matters: collect writes data/jobs.json and jobright_import
# rewrites it, so they run one after the other, never together.
cd "$(dirname "$0")" || exit 1
# One run at a time: the 7am job and a Refresh click must not overlap.
if ! mkdir data/.running 2>/dev/null; then
  if [ -n "$(find data/.running -mmin +90 2>/dev/null)" ]; then rmdir data/.running; mkdir data/.running; else echo "another run is in progress"; exit 0; fi
fi
trap 'rmdir data/.running 2>/dev/null' EXIT
echo "=== $(date '+%Y-%m-%d %H:%M') start (window ${1:-r604800}) ==="
./run collect.py --window "${1:-r604800}"  || echo "!! collect failed"
./run boards.py                            || echo "!! boards failed"
./run greenhouse_search.py                 || echo "!! greenhouse_search failed"
./run careers.py                           || echo "!! careers failed"
./run mail_alerts.py                       || echo "!! mail_alerts failed"
./run alerts_import.py                     || echo "!! alerts_import failed"
./run verify_alerts.py                     || echo "!! verify_alerts failed"
./run score.py                             || echo "!! score failed"
./run render.py                            || exit 1
[ -f data/cloud.json ] && { ./run publish.py || echo "!! publish failed"; }
[ "$NO_OPEN" = 1 ] || open http://localhost:8766/
echo "=== $(date '+%Y-%m-%d %H:%M') done ==="
