"""Local HTTP service for HiveFrame.

Standard library only. No framework, no build step, no dependency rot. The page
needs a server for three reasons: it must read files outside the browser's
reach, it will need keychain access later, and file:// blocks fetch.

Bound to 127.0.0.1. There is no auth because there is no network exposure.

What it writes, and what it does not. Every production system stays read-only;
nothing here calls Jira, ServiceNow, Concerto, Confluence or PMDW at all. The
writes are all local files: project TOMLs in the store, the decision and inbox
logs, and a file opened through the preview pane, which is fenced to the folders
this board already declares. A previous version of this docstring said
"read-only" for weeks after that stopped being true.

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

from .model import (Board, StoreError, capacity, hierarchy, rollup, score,
                    tool_usage)
from .verdict import VerdictError, capture, read_log, record_verdict
from . import edit as edits
from . import chat as chatmod
from .chat import ChatError
from .edit import EditError
from .writer import save, save_tools

WEB = Path(__file__).resolve().parent / "web"
SESSION_STATE_ROOT = Path.home() / ".copilot" / "session-state"
TREE_MAX_DEPTH = 5
# A project folder is often a repo, and a repo's real contents are a rounding
# error next to its machinery. Listing .git turns a file tree into noise.
TREE_SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__",
                  ".venv", "venv", ".mypy_cache", ".pytest_cache", ".ruff_cache",
                  ".idea", ".DS_Store", "dist", "build", ".next", ".tox"}
TREE_MAX_ENTRIES = 200

# What the file preview will open and save. Editing is only offered for text a
# person would plausibly hand-write; everything else is revealed in Finder
# instead. The list is deliberately short, because "open anything" turns a
# preview pane into an editor for files it has no business rewriting.
EDITABLE_SUFFIXES = {".md", ".txt", ".toml", ".json", ".yaml", ".yml", ".csv",
                     ".py", ".sh", ".html", ".css", ".js", ".sql", ".ini",
                     ".cfg", ".env", ".jsonl", ".xml", ".rst"}
# Past this, a browser textarea stops being a sensible way to edit anything and
# starts being a way to lose the end of a file.
EDIT_MAX_BYTES = 512 * 1024

# How a file is shown. The server decides once and the page obeys, rather than
# both of them guessing from the extension and drifting apart.
#
# "office" is honest rather than clever. A browser cannot render .pptx or .docx
# without either a conversion step or shipping the file to a cloud viewer, and
# neither belongs in a local tool holding KP material. Those open in the real
# application, one click away.
PREVIEW_KINDS = {
    ".pdf": ("pdf", "application/pdf"),
    ".png": ("image", "image/png"),
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".gif": ("image", "image/gif"),
    ".webp": ("image", "image/webp"),
    ".svg": ("image", "image/svg+xml"),
    ".heic": ("image", "image/heic"),
    ".pptx": ("office", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ".ppt": ("office", "application/vnd.ms-powerpoint"),
    ".docx": ("office", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".doc": ("office", "application/msword"),
    ".xlsx": ("office", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".xls": ("office", "application/vnd.ms-excel"),
}
# A PDF or image is streamed to the page, so it has a ceiling of its own. This
# is a local socket, but a 400 MB video would still wedge the tab.
RAW_MAX_BYTES = 64 * 1024 * 1024


def preview_kind(path: Path) -> tuple[str, str]:
    """How to show this file, and its content type.

    Returns one of: text (editable), html (renders and edits), pdf, image,
    office (open elsewhere), or none (nothing sensible to show).
    """
    suffix = path.suffix.lower()
    if suffix in (".html", ".htm"):
        return "html", "text/html; charset=utf-8"
    if suffix in PREVIEW_KINDS:
        return PREVIEW_KINDS[suffix]
    if suffix in EDITABLE_SUFFIXES:
        return "text", "text/plain; charset=utf-8"
    return "none", "application/octet-stream"


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
            "tier": p.tier,
            "parent": p.parent,
            "kind": p.kind,
            "horizon": p.horizon,
            "status": p.status,
            "store": p.store,
            "folders": [{"label": lb, "path": pt} for lb, pt in p.folders],
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
                "stop_when": p.charter.stop_when,
                "constraints": p.charter.constraints,
                "complete": p.charter_complete,
                "missing": p.charter_missing,
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

    # Containment, resolved once here rather than recomputed per card. A program
    # carries its children's state, because a program with no tasks of its own
    # is not idle if three projects beneath it are moving.
    h = hierarchy(projects)
    by_id = {p.id: p for p in projects}
    for row in ranked:
        if row["tier"] == "program":
            row["rollup"] = rollup(by_id[row["id"]], projects)

    tools = board.tools(stores)
    usage = tool_usage(tools, projects)

    return {
        "generated": date.today().isoformat(),
        "stores": list(stores),
        "projects": ranked,
        "hierarchy": h,
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

    def _session_root(self) -> Path | None:
        sid = os.environ.get("COPILOT_AGENT_SESSION_ID") or os.environ.get("HIVEFRAME_SESSION_ID")
        if not sid:
            return None
        return SESSION_STATE_ROOT / sid / "files"

    def _tree_path(self, root: Path, rel: str = "") -> Path:
        base = root.expanduser().resolve()
        target = (base / Path(rel)).resolve() if rel else base
        try:
            target.relative_to(base)
        except ValueError as e:
            raise StoreError("path escapes the selected root") from e
        return target

    def _tree_node(self, path: Path, depth: int = 0, base: Path | None = None) -> dict:
        # `rel` is what the screen shows. The absolute path is still sent,
        # because Finder and the file endpoint need it, but a reader looking at
        # a project's folder wants "notes/2026-08-18.md", not sixteen segments
        # of cloud-storage prefix they cannot act on.
        base = base or path.parent
        try:
            rel = str(path.relative_to(base))
        except ValueError:
            rel = path.name
        node = {
            "name": path.name or str(path),
            "path": str(path),
            "rel": rel,
            "kind": "dir" if path.is_dir() else "file",
            "exists": path.exists(),
        }
        if path.is_dir():
            if depth >= TREE_MAX_DEPTH:
                node["truncated"] = True
                node["children"] = []
                return node
            try:
                entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except OSError as e:
                node["error"] = str(e)
                node["children"] = []
                return node
            entries = [e for e in entries
                       if not (e.name in TREE_SKIP_DIRS or e.name.endswith(".bak"))]
            if len(entries) > TREE_MAX_ENTRIES:
                node["truncated"] = True
                node["hidden"] = len(entries) - TREE_MAX_ENTRIES
                entries = entries[:TREE_MAX_ENTRIES]
            node["children"] = [self._tree_node(child, depth + 1, base) for child in entries]
        else:
            kind, _ctype = preview_kind(path)
            node["preview"] = kind
            node["editable"] = kind in ("text", "html")
            try:
                node["size"] = path.stat().st_size
            except OSError:
                pass
        return node

    def _tree_payload(self, board: Board, scope: str = "all",
                      project_id: str = "") -> dict:
        roots = []
        note = ""
        if scope not in ("all", "work", "session", "project"):
            raise StoreError(f"unknown tree scope: {scope}")

        if scope == "project":
            if not project_id:
                raise StoreError("scope=project needs an id")
            wanted = [p for p in board.load(tuple(board.roots))
                      if p.id == project_id]
            if not wanted:
                raise StoreError(f"unknown project: {project_id}")
            p = wanted[0]
            for label, folder in p.folders:
                path = Path(folder).expanduser()
                roots.append({
                    "label": label,
                    "path": str(path),
                    "exists": path.exists(),
                    "tree": self._tree_node(path),
                })
            if not roots:
                if p.source_file:
                    roots.append({
                        "label": "Project file",
                        "path": str(p.source_file),
                        "exists": Path(p.source_file).exists(),
                        "tree": self._tree_node(Path(p.source_file)),
                    })
                note = ("No folder declared for this project. Add "
                        'folder = "/path/..." under [project], or an artifact '
                        "whose path is a directory.")
            return {"generated": date.today().isoformat(),
                    "project": p.id, "roots": roots, "note": note}

        if scope in ("all", "work"):
            root = board.root_for("work")
            roots.append({
                "label": "Work store",
                "path": str(root),
                "exists": root.exists(),
                "tree": self._tree_node(root),
            })

        if scope in ("all", "session"):
            root = self._session_root()
            if root is not None:
                roots.append({
                    "label": "Session artifacts",
                    "path": str(root),
                    "exists": root.exists(),
                    "tree": self._tree_node(root),
                })

        if not roots:
            raise StoreError("no tree roots available")
        return {"generated": date.today().isoformat(), "roots": roots}

    def _file_roots(self, board: Board) -> list[Path]:
        """Every directory the file endpoint may read or write inside.

        Exactly the roots the tree already exposes: each store root, plus each
        folder a project declares. Nothing is reachable that was not already
        browsable, so the preview cannot widen the blast radius of the view it
        opens from.
        """
        out: list[Path] = []
        for name in board.roots:
            try:
                out.append(board.root_for(name).expanduser().resolve())
            except StoreError:
                continue
        for p in board.load(tuple(board.roots)):
            for _label, folder in p.folders:
                try:
                    out.append(Path(folder).expanduser().resolve())
                except OSError:
                    continue
        return out

    def _resolve_in_roots(self, board: Board, target: str) -> tuple[Path, Path]:
        """Resolve a requested path, or refuse it.

        Resolution happens before the containment check, so a symlink or a
        `..` segment is compared as its real destination rather than as the
        string someone sent. Returns the file and the root it sits under, since
        the caller wants the relative path for display.
        """
        if not target:
            raise StoreError("no path given")
        path = Path(target).expanduser().resolve()
        for root in self._file_roots(board):
            try:
                path.relative_to(root)
            except ValueError:
                continue
            return path, root
        raise StoreError("path is outside every project folder on this board")

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

        if u.path == "/api/tree":
            scope = q.get("scope", ["all"])[0]
            pid = q.get("id", [""])[0]
            try:
                return self._json(self._tree_payload(Board.from_env(), scope, pid))
            except StoreError as e:
                return self._json({"error": str(e)}, 400)

        if u.path == "/api/file":
            # Metadata plus, for text, the text itself. Binary formats are not
            # returned here; the page asks /api/raw for those, because base64
            # in a JSON envelope is a third larger and buys nothing.
            try:
                path, root = self._resolve_in_roots(Board.from_env(),
                                                    q.get("path", [""])[0])
            except StoreError as e:
                return self._json({"error": str(e)}, 400)
            if not path.is_file():
                return self._json({"error": "not a file"}, 404)
            try:
                size = path.stat().st_size
            except OSError as e:
                return self._json({"error": str(e)}, 400)
            kind, ctype = preview_kind(path)
            meta = {"path": str(path), "name": path.name,
                    "rel": str(path.relative_to(root)), "size": size,
                    "kind": kind, "content_type": ctype}

            if kind in ("pdf", "image"):
                if size > RAW_MAX_BYTES:
                    return self._json({**meta, "kind": "none", "editable": False,
                                       "reason": f"{size} bytes, too large to show here"})
                return self._json({**meta, "editable": False})

            if kind == "office":
                return self._json({**meta, "editable": False,
                                   "reason": "PowerPoint, Word and Excel files "
                                             "open in their own application"})

            if kind == "none":
                return self._json({**meta, "editable": False,
                                   "reason": "not a format HiveFrame can show"})

            # text and html: both are read as text and both are editable.
            if size > EDIT_MAX_BYTES:
                return self._json({**meta, "editable": False,
                                   "reason": f"{size} bytes, too large to edit here"})
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                return self._json({**meta, "kind": "none", "editable": False,
                                   "reason": f"cannot read as text: {e}"})
            return self._json({**meta, "editable": True, "text": text})

        if u.path == "/api/raw":
            # The bytes, for a PDF, an image, or an HTML page being rendered.
            # Same fence as /api/file: resolve first, then require the result to
            # sit inside a declared folder.
            try:
                path, _root = self._resolve_in_roots(Board.from_env(),
                                                     q.get("path", [""])[0])
            except StoreError as e:
                return self._json({"error": str(e)}, 400)
            if not path.is_file():
                return self._json({"error": "not a file"}, 404)
            kind, ctype = preview_kind(path)
            if kind == "none":
                return self._json({"error": "not a format HiveFrame can show"}, 400)
            try:
                blob = path.read_bytes()
            except OSError as e:
                return self._json({"error": str(e)}, 400)
            if len(blob) > RAW_MAX_BYTES:
                return self._json({"error": "file is too large to show here"}, 413)
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(blob)))
            # Inline, so it renders in the panel instead of downloading. The
            # filename is quoted because a real one contains spaces.
            self.send_header("Content-Disposition",
                             f'inline; filename="{path.name}"')
            # A local page reading a local file. No embedding anywhere else.
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.end_headers()
            self.wfile.write(blob)
            return

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
                "allow_all_tools": chatmod.ALLOW_ALL_TOOLS,
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

        if u.path == "/api/file":
            # Save an edited file back. Same containment rule as the read, and
            # a .bak alongside, because the fastest way to make someone stop
            # trusting an in-page editor is to lose one version of one file.
            try:
                path, root_dir = self._resolve_in_roots(board, data.get("path", ""))
            except StoreError as e:
                return self._json({"error": str(e)}, 400)
            if not path.is_file():
                return self._json({"error": "not a file"}, 404)
            if path.suffix.lower() not in EDITABLE_SUFFIXES:
                return self._json({"error": "not a file type HiveFrame edits"}, 400)
            text = data.get("text")
            if not isinstance(text, str):
                return self._json({"error": "no text given"}, 400)
            try:
                path.with_suffix(path.suffix + ".bak").write_text(
                    path.read_text(encoding="utf-8"), encoding="utf-8")
                path.write_text(text, encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"ok": True, "path": str(path),
                               "rel": str(path.relative_to(root_dir)),
                               "bytes": len(text.encode("utf-8"))})

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

    # The file preview can reach only what the tree already shows. This is the
    # check that matters most in this feature: it turned a read-only browser
    # into something that writes, and the containment rule is the only thing
    # standing between "edit a project note" and "edit anything on the disk".
    h = Handler.__new__(Handler)
    roots = h._file_roots(board)
    if not roots:
        print("  FAIL: file preview has no roots, so nothing would open")
        return 1
    for bad in ("/etc/passwd", str(Path.home() / ".ssh" / "id_rsa"),
                str(roots[0]) + "/../../../etc/hosts"):
        try:
            h._resolve_in_roots(board, bad)
            print(f"  FAIL: file preview accepted a path outside its roots: {bad}")
            return 1
        except StoreError:
            pass
    print(f"  file preview is fenced to {len(roots)} declared folder(s); "
          "traversal and outside paths refused")

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

    # The file view is scoped to the project in focus, so every path it offers
    # must belong to that project and must be a directory that exists.
    store_root = Path(board.roots["work"]).expanduser().resolve()
    for p in projects:
        for label, folder in p.folders:
            fp = Path(folder).expanduser()
            if not fp.is_dir():
                print(f"  FAIL: {p.id} folder is not a directory: {folder}")
                return 1
            if p.folder and fp.resolve() == store_root:
                print(f"  FAIL: {p.id} declares the whole work store as its folder")
                return 1
    scoped = sum(1 for p in projects if p.folders)
    print(f"  folder scope: {scoped}/{len(projects)} project(s) resolve to their own folder")

    cap = capacity(projects, 10.0)
    print(f"  capacity: {cap['committed_h']}h committed against "
          f"{cap['available_h']}h available over {cap['window_days']}d "
          f"({cap['operations_h']}h taken off the top for operations)")
    print(f"  at risk: {len(cap['at_risk'])} task(s)")

    # Containment must resolve. A dangling or wrongly-aimed parent hides a
    # project under nothing, which is exactly how the WBS work stayed off the
    # board for weeks.
    h = hierarchy(projects)
    if h["problems"]:
        for pr in h["problems"]:
            print(f"  FAIL: {pr['project']}: {pr['issue']}")
        return 1
    tiers = {}
    for p in projects:
        tiers[p.tier] = tiers.get(p.tier, 0) + 1
    print("  hierarchy: " + ", ".join(f"{n} {t}" for t, n in sorted(tiers.items()))
          + f"; {len(h['roots'])} at the top, no orphans or cycles")

    # An operation must never carry a rank. It is subtracted in capacity, and
    # ranking it as well would count the same hours twice and offer a choice
    # that is not really available.
    for p in projects:
        if p.is_operation:
            assert score(p)[0] == 0.0, f"{p.id} is an operation and must not be ranked"
    print("  operations are taken off the top, not ranked against projects")

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
    # Tools are broad and reach is narrow, so the assertion worth making is
    # about the network: nothing leaves this machine and nothing is published
    # from the chat rail. Local deletion is deliberately not asserted, because
    # testing showed the edit tool deletes when shell(rm) is refused, and an
    # assertion that passes while the protection does not hold is worse than
    # no assertion. Git is the recovery.
    for verb in ("shell(curl)", "shell(ssh)", "shell(git push)", "shell(rsync)"):
        assert verb in chatmod.DENY_TOOLS, f"{verb} must stay denied"
    assert chatmod.DEFAULT_MODEL == chatmod.MODELS[0][0], "default must be the cheapest model"
    print("  chat can write and run local commands; the network stays closed")

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
    print("  writes local files only, no live system. Ctrl-C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
