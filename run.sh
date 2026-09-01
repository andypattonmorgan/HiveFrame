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
# Three environment facts are set here rather than inherited, because all three
# have failed silently at least once:
#
#   PATH   The VS Code terminal's PATH does not always carry /opt/homebrew/bin.
#          chat.available() resolves the CLI with shutil.which("copilot"), so a
#          short PATH reports "copilot CLI not found" and the UI greys out the
#          send button. copilot is a Node loader script, so node must resolve
#          from the same directory; half the fix is no fix.
#
#   stdin  nohup leaves stdin attached to the terminal. If that terminal is
#          later interrupted, every request hangs with an empty log, which
#          reads like a dead server rather than a blocked one.
#
#   store  Board.load() skips a root that does not exist and returns an empty
#          list. A mistyped path is indistinguishable from an empty board, so
#          it looks like the portfolio was lost. Checked before starting.
#
# Usage:
#   ./run.sh              work store, port 8787
#   PORT=9000 ./run.sh    another port
#   ./run.sh --fg         foreground, for reading tracebacks live

set -e

PORT="${PORT:-8787}"
PY="${PY:-/opt/homebrew/bin/python3.14}"

# Homebrew first, then the standard set. Prepended rather than replaced so a
# deliberate override still wins.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# The work store lives outside this repo on purpose: the tool is public, the
# portfolio is not. It sits under KaiserKM rather than KPKM because it is the
# tool's operating data, holding every project's board, and not the content of
# any one project. The HiveFrame *project* (planning, meetings, decisions about
# building this) is a separate thing and lives at KPKM/HiveFrame.
export HIVEFRAME_WORK="${HIVEFRAME_WORK:-/Users/D112236/Library/CloudStorage/OneDrive-KaiserPermanente/KaiserKM/hiveframe-store/projects}"

cd "$(dirname "$0")"

# Refuse to start on a store that is not there. Serving an empty board on a
# mistyped path is the failure that looks like data loss.
if [[ ! -d "$HIVEFRAME_WORK" ]]; then
  /bin/echo "store directory does not exist:"
  /bin/echo "  $HIVEFRAME_WORK"
  /bin/echo "Not starting. An empty board and a wrong path look identical once served."
  exit 1
fi

TOML_COUNT=$(/bin/ls "$HIVEFRAME_WORK"/*.toml 2>/dev/null | /usr/bin/wc -l | /usr/bin/tr -d ' ')
if [[ "$TOML_COUNT" == "0" ]]; then
  /bin/echo "warning: no .toml projects in $HIVEFRAME_WORK"
fi

# Report the CLI up front. Not fatal: the board is useful without chat, and a
# named cause beats a greyed-out button with no explanation.
if ! command -v copilot > /dev/null 2>&1; then
  /bin/echo "warning: copilot not on PATH, chat send will be disabled"
elif ! command -v node > /dev/null 2>&1; then
  /bin/echo "warning: node not on PATH, the copilot loader will fail"
fi

/usr/bin/pkill -9 -f "hiveframe.server" 2>/dev/null || true
/usr/bin/pkill -9 -f "copilot" 2>/dev/null || true
/bin/sleep 1

if [[ "$1" == "--fg" ]]; then
  exec "$PY" -m hiveframe.server --port "$PORT"
fi

# -u so the log is readable while it is still running. stdin from /dev/null so
# an interrupted parent terminal cannot stall the request loop.
/usr/bin/nohup "$PY" -u -m hiveframe.server --port "$PORT" \
  > /tmp/hiveframe.log 2>&1 < /dev/null &
disown
/bin/sleep 2

if /usr/sbin/lsof -nP -iTCP:"$PORT" -sTCP:LISTEN > /dev/null 2>&1; then
  /bin/echo "HiveFrame on http://127.0.0.1:$PORT  (log: /tmp/hiveframe.log)"
  /bin/echo "store: $HIVEFRAME_WORK  ($TOML_COUNT projects)"
  # Listening is not the same as answering. One cheap request proves the loop
  # is actually serving rather than blocked before the first accept.
  CODE=$(/usr/bin/curl -s --max-time 10 -o /dev/null -w "%{http_code}" \
         "http://127.0.0.1:$PORT/" || true)
  if [[ "$CODE" != "200" ]]; then
    /bin/echo "listening but not answering (got '$CODE'), see /tmp/hiveframe.log"
    exit 1
  fi
  # Ask the server, not the shell, whether chat is usable. That is the exact
  # value the UI reads to decide whether Send is clickable.
  if /usr/bin/curl -s --max-time 20 "http://127.0.0.1:$PORT/api/chat/state?store=work" \
     | /usr/bin/grep -q '"ok": *true'; then
    /bin/echo "chat: ready"
  else
    /bin/echo "chat: send disabled, run 'copilot --version' to see why"
  fi
else
  /bin/echo "did not come up, see /tmp/hiveframe.log"
  /usr/bin/tail -20 /tmp/hiveframe.log
  exit 1
fi
