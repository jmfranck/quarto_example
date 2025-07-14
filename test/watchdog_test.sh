#!/bin/bash
set -e
python3 -u fast_build.py --watch --no-browser > /tmp/watchdog.log 2>&1 &
PID=$!
# give the server time to start
sleep 5
# add a unique marker
MARK="WATCHDOG_TEST_$(date +%s)"
echo "$MARK" >> project1/subproject1/tasks.qmd
# wait for rebuild
sleep 5
kill $PID
# verify the marker appears in built HTML
grep -q "$MARK" _build/projects.html
