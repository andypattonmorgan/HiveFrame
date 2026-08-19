#!/bin/zsh
#
# Start HiveFrame, detached.
#
# This exists because of a terminal quirk that costs an hour every time it is
# rediscovered. The VS Code integrated terminal suspends a foreground server the
# moment it writes to the tty, and a suspended process still holds the port
# without accepting connections. The result looks exactly like a network
# failure: connection refused turns into connection timeout, and the obvious
# next move, restarting, fails too because the port is taken by something that
# looks dead and is not. nohup plus disown avoids the whole class of problem.
#
# Old copilot processes are killed alongside the server. A chat turn spawns
# child processes that outlive an abrupt server exit, and they hold pipes open,
# which is its own confusing failure the next time round.
#
# Usage:
#   ./run.sh              work store, port 8787
#   PORT=9000 ./run.sh    another port
#   ./run.sh --fg         foreground, for reading tracebacks live

set -e

PORT="${PORT:-8787}"
PY="${PY:-/opt/homebrew/bin/python3.14}"

# The work store lives outside this repo on purpose: the tool is public, the
# portfolio is not. It sits under KaiserKM rather than KPKM because it is the
# tool's operating data, holding every project's board, and not the content of
# any one project. The HiveFrame *project* (planning, meetings, decisions about
# building this) is a separate thing and lives at KPKM/HiveFrame.
export HIVEFRAME_WORK="${HIVEFRAME_WORK:-/Users/D112236/Library/CloudStorage/OneDrive-KaiserPermanente/KaiserKM/hiveframe-store/projects}"

cd "$(dirname "$0")"

/usr/bin/pkill -9 -f "hiveframe.server" 2>/dev/null || true
/usr/bin/pkill -9 -f "copilot" 2>/dev/null || true
/bin/sleep 1

if [[ "$1" == "--fg" ]]; then
  exec "$PY" -m hiveframe.server --port "$PORT"
fi

/usr/bin/nohup "$PY" -m hiveframe.server --port "$PORT" > /tmp/hiveframe.log 2>&1 &
disown
/bin/sleep 2

if /usr/sbin/lsof -nP -iTCP:"$PORT" -sTCP:LISTEN > /dev/null 2>&1; then
  /bin/echo "HiveFrame on http://127.0.0.1:$PORT  (log: /tmp/hiveframe.log)"
  /bin/echo "store: $HIVEFRAME_WORK"
else
  /bin/echo "did not come up, see /tmp/hiveframe.log"
  /usr/bin/tail -20 /tmp/hiveframe.log
  exit 1
fi
