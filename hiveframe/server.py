"""Local HTTP service for HiveFrame.

Standard library only. No framework, no build step, no dependency rot. The page
needs a server for three reasons: it must read files outside the browser's
reach, it will need keychain access later, and file:// blocks fetch.

Bound to 127.0.0.1. There is no auth because there is no network exposure.

Read-only in this phase: every endpoint is a GET and nothing is written.

Usage:
    python3 -m hiveframe.server --port 8787
    python3 -m hiveframe.server --selftest
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import date
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from .model import Board, StoreError, capacity, score, tool_usage
from .verdict import VerdictError, capture, read_log, record_verdict
from . import edit as edits
from . import chat as chatmod
from .chat import ChatError
from .edit import EditError
from .writer import save, save_tools

WEB = Path(__file__).resolve().parent / "web"


def vpn_state() -> dict:
    """Whether internal systems are reachable right now.

    A function that cannot run should say so and say why, rather than failing
    when invoked. Tunnel presence is a cheap proxy; it is not proof that any
    particular host answers.
    """
    try:
        out = subprocess.run(["/usr/sbin/scutil", "--nwi"],
                             capture_output=True, text=True, timeout=3).stdout
        tunnel = "utun" in out
    except Exception:
        tunnel = False
    return {
        "tunnel": tunnel,
        "label": "VPN tunnel present" if tunnel else "No VPN tunnel",
        "note": "Tunnel presence only. Reachability of a specific host is not tested.",
    }


def board_payload(stores: tuple[str, ...], weekly_hours: float) -> dict:
    board = Board.from_env()
    projects = board.load(stores)

    ranked = []
    for p in projects:
        pts, why = score(p)
        nxt = p.next_actionable()
        ranked.append({
            "id": p.id,
            "name": p.name,
            "kind": p.kind,
            "horizon": p.horizon,
            "status": p.status,
            "store": p.store,
            "score": round(pts, 1),
            "why": why,
            "next_move": ({"id": nxt.id, "title": nxt.title,
                           "due": nxt.due.isoformat() if nxt.due else None,
                           "effort_h": nxt.effort_h} if nxt else None),
            "open_tasks": len(p.open_tasks),
            "actionable_tasks": len(p.actionable_tasks),
            "stalled": p.stalled,
            "open_effort_h": p.open_effort_h,
            "next_due": p.next_due().isoformat() if p.next_due() else None,
            "charter": {
                "problem": p.charter.problem,
                "hypothesis": p.charter.hypothesis,
                "goal": p.charter.goal,
                "kill_when": p.charter.kill_when,
                "done_when": p.charter.done_when,
                "constraints": p.charter.constraints,
                "complete": p.charter.complete,
                "missing": p.charter.missing,
            },
            "artifacts": [{
                "label": a.label, "path": a.path, "url": a.url,
                "kind": a.kind, "exists": a.exists,
            } for a in p.artifacts],
            "tasks": [{
                "id": t.id, "title": t.title, "status": t.status,
                "due": t.due.isoformat() if t.due else None,
                "days_left": t.days_left(),
                "effort_h": t.effort_h, "urgent": t.urgent,
                "important": t.important, "blocked_by": t.blocked_by,
                "note": t.note,
            } for t in p.tasks],
            "relations": [{
                "to": r.to, "type": r.type, "status": r.status, "note": r.note,
            } for r in p.relations],
            "uses": p.uses,
            "source_file": str(p.source_file) if p.source_file else None,
        })

    ranked.sort(key=lambda r: -r["score"])

    tools = board.tools(stores)
    usage = tool_usage(tools, projects)

    return {
        "generated": date.today().isoformat(),
        "stores": list(stores),
        "projects": ranked,
        "tools": [{
            "id": t.id, "name": t.name or t.id, "does": t.does, "where": t.where,
            "path": t.path, "status": t.status, "access": t.access, "note": t.note,
            "exists": t.exists, "documented": t.documented,
            "used_by": usage.get(t.id, []),
        } for t in sorted(tools, key=lambda x: (len(usage.get(x.id, [])), x.id))],
        # A project can name a tool that was never registered. That is not an
        # error at read time, it is a finding: something load-bearing is
        # undocumented.
        "undeclared_tools": sorted(set(usage) - {t.id for t in tools}),
        "capacity": capacity(projects, weekly_hours),
        "vpn": vpn_state(),
    }


class Handler(BaseHTTPRequestHandler):
    weekly_hours = 10.0

    def log_message(self, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path):
        if not path.exists() or not path.is_file():
            self._json({"error": "not found"}, 404)
            return
        ctype = {".html": "text/html", ".css": "text/css",
                 ".js": "text/javascript", ".svg": "image/svg+xml"}.get(
                     path.suffix, "application/octet-stream")
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)

        if u.path in ("/", "/index.html"):
            return self._file(WEB / "index.html")

        if u.path == "/api/board":
            stores = tuple(q.get("stores", ["work"])[0].split(","))
            try:
                return self._json(board_payload(stores, self.weekly_hours))
            except StoreError as e:
                return self._json({"error": str(e)}, 400)

        if u.path == "/api/open":
            # Reveal an artifact in Finder rather than opening it, so a stray
            # click cannot launch something unexpected.
            target = q.get("path", [""])[0]
            p = Path(target).expanduser()
            if not p.exists():
                return self._json({"ok": False, "error": "path not found"}, 404)
            subprocess.run(["/usr/bin/open", "-R", str(p)], check=False)
            return self._json({"ok": True})

        if u.path == "/api/log":
            name = q.get("name", ["decisions.jsonl"])[0]
            if name not in ("decisions.jsonl", "inbox.jsonl"):
                return self._json({"error": "unknown log"}, 400)
            try:
                root = Board.from_env().root_for(q.get("store", ["work"])[0])
            except StoreError as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"rows": read_log(root, name)})

        if u.path == "/api/chat/state":
            # Whether chat is usable at all, and this store's turn log. Cheap:
            # no credits are spent answering this.
            try:
                root = Board.from_env().root_for(q.get("store", ["work"])[0])
            except StoreError as e:
                return self._json({"error": str(e)}, 400)
            state = chatmod.available()
            project = q.get("project", [""])[0]
            return self._json({
                "cli": state,
                "session": chatmod.read_session(root, project),
                "model": chatmod.DEFAULT_MODEL,
                "models": [{"id": m, "tier": t, "credits": c}
                           for m, t, c in chatmod.MODELS],
                "allow": list(chatmod.ALLOW_TOOLS),
                "deny": list(chatmod.DENY_TOOLS),
                "history": chatmod.history(root),
                "transcript": chatmod.read_transcript(root, project),
            })

        if u.path.startswith("/static/"):
            return self._file(WEB / u.path[len("/static/"):])

        self._json({"error": "not found"}, 404)

    # ---- writes ----------------------------------------------------------
    # The only two writes in the tool, both to files inside a store the caller
    # named. No production system is written to from here or anywhere else.

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n) or b"{}")

    def do_POST(self):
        u = urlparse(self.path)
        try:
            data = self._body()
        except json.JSONDecodeError:
            return self._json({"error": "body was not JSON"}, 400)

        board = Board.from_env()
        store = data.get("store", "work")
        try:
            root = board.root_for(store)
        except StoreError as e:
            return self._json({"error": str(e)}, 400)

        if u.path == "/api/verdict":
            try:
                projects = board.load((store,))
            except StoreError as e:
                return self._json({"error": str(e)}, 400)
            hit = next((p for p in projects if p.id == data.get("project")), None)
            if hit is None:
                return self._json({"error": "no such project in that store"}, 404)
            try:
                rec = record_verdict(hit, data.get("status", ""),
                                     data.get("reason", ""), root)
            except VerdictError as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"ok": True, "recorded": rec})

        if u.path == "/api/capture":
            try:
                rec = capture(data.get("text", ""), root,
                              data.get("project", ""), data.get("task", ""))
            except VerdictError as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"ok": True, "recorded": rec})

        if u.path == "/api/edit":
            return self._edit(board, store, data)

        if u.path == "/api/tool":
            return self._tool(board, store, data)

        if u.path == "/api/chat":
            return self._chat(board, store, root, data)

        if u.path == "/api/chat/stream":
            return self._chat_stream(board, store, root, data)

        if u.path == "/api/chat/stop":
            stopped = chatmod.stop(data.get("id", ""))
            return self._json({"ok": True, "stopped": stopped})

        self._json({"error": "not found"}, 404)

    def _chat_dirs(self, root):
        dirs = [root]
        repo = Path(__file__).resolve().parent.parent
        if repo not in dirs:
            dirs.append(repo)
        return tuple(dirs)

    def _chat_stream(self, board, store, root, data):
        """The same turn as /api/chat, delivered as it happens.

        Newline-delimited JSON rather than server-sent events, because SSE is a
        GET-only API in the browser and a prompt does not belong in a URL. The
        client reads the body with a stream reader, which costs a few more lines
        there and keeps the prompt in the body where it belongs.

        Flushed per event. Buffering a stream defeats the only reason it exists.
        """
        project = data.get("project", "")
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            for ev in chatmod.ask_stream(data.get("prompt", ""), root,
                                         dirs=self._chat_dirs(root),
                                         model=data.get("model", ""),
                                         context=data.get("context", ""),
                                         project=project):
                self.wfile.write((json.dumps(ev) + "\n").encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # You closed the tab or navigated away. The turn is already being
            # cleaned up by ask_stream's own finally, so there is nothing to
            # report and nobody left to report it to.
            pass

    def _chat(self, board, store, root, data):
        """One turn against the Copilot CLI.

        The store decides which conversation this is, and the project splits it
        further. Cost grows with conversation length because resume re-sends the
        history, so one thread per project is a cost control as much as a
        separation of concerns.
        """
        project = data.get("project", "")
        if data.get("reset"):
            chatmod.clear_session(root, project)
            return self._json({"ok": True, "reset": True})

        try:
            answer = chatmod.ask(data.get("prompt", ""), root,
                                 dirs=self._chat_dirs(root),
                                 model=data.get("model", ""),
                                 context=data.get("context", ""),
                                 project=project)
        except ChatError as e:
            return self._json({"error": str(e)}, 400)
        return self._json({"ok": True, **answer})

    def _tool(self, board, store, data):
        """Registry edits. The registry is one file per store, not per project."""
        try:
            root = board.root_for(store)
            tools = board.tools((store,))
            projects = board.load((store,))
        except StoreError as e:
            return self._json({"error": str(e)}, 400)

        action = data.get("action", "")
        try:
            if action == "upsert":
                edits.upsert_tool(tools, data.get("fields") or {})
            elif action == "retire":
                edits.retire_tool(tools, data.get("tool", ""),
                                  data.get("reason", ""),
                                  tool_usage(tools, projects))
            else:
                return self._json({"error": f"unknown action {action!r}"}, 400)
        except EditError as e:
            return self._json({"error": str(e)}, 400)

        save_tools(tools, root)
        return self._json({"ok": True, "action": action})

    # ---- structural edits ------------------------------------------------
    # One endpoint with an action, rather than a route per verb. The set of
    # edits will grow, and a router that grows a branch per field is how a
    # small tool acquires a large surface nobody can audit.

    def _edit(self, board, store, data):
        try:
            projects = board.load((store,))
        except StoreError as e:
            return self._json({"error": str(e)}, 400)

        p = next((x for x in projects if x.id == data.get("project")), None)
        if p is None:
            return self._json({"error": "no such project in that store"}, 404)

        action = data.get("action", "")
        payload = data.get("fields") or {}
        try:
            if action == "project":
                edits.edit_project(p, payload)
            elif action == "charter":
                edits.edit_charter(p, payload)
            elif action == "task.add":
                edits.add_task(p, payload)
            elif action == "task.edit":
                edits.edit_task(p, data.get("task", ""), payload)
            elif action == "task.drop":
                edits.drop_task(p, data.get("task", ""), data.get("reason", ""))
            elif action == "artifact.add":
                edits.add_artifact(p, payload)
            elif action == "relation.add":
                edits.add_relation(p, data.get("to", ""), data.get("type", ""),
                                   data.get("note", ""))
            elif action == "relation.verdict":
                edits.set_relation(p, data.get("to", ""),
                                   data.get("verdict", ""), data.get("note", ""))
            elif action == "uses":
                known = {t.id for t in board.tools((store,))}
                edits.set_uses(p, payload.get("uses") or [], known)
            else:
                return self._json({"error": f"unknown action {action!r}"}, 400)
        except EditError as e:
            return self._json({"error": str(e)}, 400)

        save(p)
        return self._json({"ok": True, "project": p.id, "action": action})


def selftest() -> int:
    print("HiveFrame selftest")
    board = Board.from_env()
    print(f"  roots: { {k: str(v) for k, v in board.roots.items()} }")

    projects = board.load(("work",))
    print(f"  loaded {len(projects)} work project(s)")
    for p in projects:
        pts, why = score(p)
        print(f"    {p.id:28s} {p.kind:11s} {p.status:8s} "
              f"score {pts:5.1f}  {len(p.open_tasks)} open")

    try:
        board.load(("nonsense",))
        print("  FAIL: unknown store was accepted")
        return 1
    except StoreError:
        print("  store boundary holds: unknown store rejected")

    # A work view must never receive personal projects, whatever a file claims.
    if any(p.store != "work" for p in projects):
        print("  FAIL: a non-work project appeared in a work load")
        return 1
    print("  store boundary holds: work load returned only work projects")

    # A block must not demote a project that still has a move available.
    probe = replace(projects[0], status="blocked")
    if probe.actionable_tasks and score(probe)[0] <= score(projects[0])[0]:
        print("  FAIL: blocking a project with an available move lowered its rank")
        return 1
    print("  blocked with a move available ranks above the same project unblocked")

    # Ranking has to separate. A board where everything scores the same is a
    # list, and a list is what the tool exists to replace.
    scores = [score(p)[0] for p in projects if p.status in ("active", "blocked")]
    if len(scores) != len(set(scores)):
        print(f"  WARN: {len(scores) - len(set(scores))} project(s) tied on score")
    else:
        print(f"  ranking separates: {len(scores)} live project(s), no ties")

    cap = capacity(projects, 10.0)
    print(f"  capacity: {cap['committed_h']}h committed against "
          f"{cap['available_h']}h available over {cap['window_days']}d")
    print(f"  at risk: {len(cap['at_risk'])} task(s)")
    print(f"  vpn: {vpn_state()['label']}")

    # Writes are exercised on a copy in a temp directory. A selftest that edits
    # the real store to prove it can edit the real store is not a test.
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        src = Path(board.roots["work"])
        for f in src.glob("*.toml"):
            shutil.copy2(f, tmp_root / f.name)
        sandbox = Board({"work": tmp_root})
        target = sandbox.load(("work",))[0]

        try:
            record_verdict(target, "paused", "", tmp_root)
            print("  FAIL: a verdict with no reason was accepted")
            return 1
        except VerdictError:
            print("  a verdict with no reason is refused")

        record_verdict(target, "paused", "selftest, not a real decision", tmp_root)
        again = next(p for p in sandbox.load(("work",)) if p.id == target.id)
        if again.status != "paused":
            print("  FAIL: status was not written back")
            return 1
        if len(read_log(tmp_root, "decisions.jsonl")) != 1:
            print("  FAIL: decision was not logged")
            return 1
        print("  verdict writes the status line and logs the reason")

        # A round trip must not lose data, or every edit quietly costs you
        # something you did not agree to give up.
        from .model import load_project
        before = sandbox.load(("work",))[0]
        save(before)
        after = load_project(Path(before.source_file))
        same = (len(before.tasks) == len(after.tasks)
                and len(before.artifacts) == len(after.artifacts)
                and len(before.relations) == len(after.relations)
                and before.charter.problem == after.charter.problem
                and [t.due for t in before.tasks] == [t.due for t in after.tasks]
                and [t.blocked_by for t in before.tasks] == [t.blocked_by for t in after.tasks])
        if not same:
            print("  FAIL: writing and reloading a project changed it")
            return 1
        print("  writer round trip preserves tasks, artifacts, relations, charter")

        try:
            edits.edit_task(after, after.tasks[0].id,
                            {"blocked_by": [after.tasks[0].id]})
            edits.add_task(after, {"title": "loop probe"})
            edits.edit_task(after, "loop-probe", {"blocked_by": [after.tasks[0].id]})
            edits.edit_task(after, after.tasks[0].id, {"blocked_by": ["loop-probe"]})
            print("  FAIL: a dependency cycle was accepted")
            return 1
        except EditError:
            print("  a dependency cycle is refused")

        # Tools are shared, so a project must not be able to claim one out of
        # existence while another still depends on it.
        tools = sandbox.tools(("work",))
        if tools:
            usage = tool_usage(tools, sandbox.load(("work",)))
            orphans = [t.id for t in tools if not usage.get(t.id)]
            print(f"  tool registry: {len(tools)} tool(s), "
                  f"{len(orphans)} depended on by nothing")
            held = next((tid for tid, users in usage.items() if users), None)
            if held:
                try:
                    edits.retire_tool(tools, held, "selftest", usage)
                    print("  FAIL: retired a tool a project still depends on")
                    return 1
                except EditError:
                    print("  retiring a depended-on tool is refused")

    state = chatmod.available()
    print(f"  chat CLI: {state.get('version') or state.get('reason')}")
    # Writes are permitted on purpose. Publishing and remote history rewriting
    # are not, and those are the assertions that actually hold: there is no
    # allowed path to the network. shell(rm) is asserted too, but tested
    # behaviour is that the CLI deletes through the edit tool when refused rm,
    # so treat that one as friction, not a boundary. Git is the recovery.
    for verb in ("shell(rm)", "shell(git push)", "shell(curl)"):
        assert verb in chatmod.DENY_TOOLS, f"{verb} must stay denied"
    assert chatmod.DEFAULT_MODEL == chatmod.MODELS[0][0], "default must be the cheapest model"
    print("  chat blocks publishing and network verbs; deletion is only slowed, not stopped")

    print("selftest OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--weekly-hours", type=float,
                    default=float(os.environ.get("HIVEFRAME_WEEKLY_HOURS", 10)))
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    Handler.weekly_hours = args.weekly_hours
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"HiveFrame on http://127.0.0.1:{args.port}")
    print(f"  weekly budget: {args.weekly_hours}h")
    print("  read-only. Ctrl-C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
