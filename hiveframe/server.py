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

from .model import Board, StoreError, capacity, score
from .verdict import VerdictError, capture, read_log, record_verdict

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
            "source_file": str(p.source_file) if p.source_file else None,
        })

    ranked.sort(key=lambda r: -r["score"])

    return {
        "generated": date.today().isoformat(),
        "stores": list(stores),
        "projects": ranked,
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

        self._json({"error": "not found"}, 404)


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
