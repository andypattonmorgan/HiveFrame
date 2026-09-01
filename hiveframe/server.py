"""Local HTTP service for HiveFrame.

Standard library only. No framework, no build step, no dependency rot. The page
needs a server for three reasons: it must read files outside the browser's
reach, it will need keychain access later, and file:// blocks fetch.

Bound to 127.0.0.1. There is no auth because there is no network exposure.

What it writes, and what it does not. Every production system stays read-only.
One of them is now reachable from here: Confluence, through GET-only reads in
hiveframe/confluence.py, so a project can cite the page of record instead of a
local copy of it. Nothing here calls Jira, ServiceNow, Concerto or PMDW. The
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
import base64
import binascii
import json
import os
import subprocess
import sys
import tempfile
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
from . import carry as carrymod
from . import chat as chatmod
from . import confluence as confmod
from .confluence import ConfluenceError
from .carry import CarryError
from .chat import ChatError
from .edit import EditError
from .writer import save, save_tools

WEB = Path(__file__).resolve().parent / "web"
SESSION_STATE_ROOT = Path.home() / ".copilot" / "session-state"
# The morning routine is an existing KaiserKM tool, outside this repo. Override
# with HIVEFRAME_MORNING_SCRIPT rather than editing this line.
MORNING_SCRIPT = Path(os.environ.get(
    "HIVEFRAME_MORNING_SCRIPT",
    Path.home() / "Library" / "CloudStorage"
    / "OneDrive-KaiserPermanente" / "KaiserKM" / "tools" / "start-my-day"
    / "start_my_day.py")).expanduser()
MORNING_TIMEOUT_S = 300
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
            "folders": [{"label": lb, "path": pt, "mode": md}
                        for lb, pt, md in p.folder_roots],
            "home": p.home_folder or "",
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
                "files": t.files,
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
        # Named so the assistant does not have to guess it. Left to guess, it
        # invents a plausible path and presents the invention as instructions.
        "store_root": str(board.root_for(stores[0])) if stores else "",

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

    def handle_one_request(self):
        # A browser that navigates away, reloads, or stops a request leaves the
        # server writing into a closed socket. That is the client's normal
        # behaviour, not a fault here, and the default handler prints a full
        # traceback for it. Real faults get buried in that noise, so the two
        # disconnect errors are swallowed and everything else still raises.
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

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
        # This is a local dev server and every file it serves is one you are
        # editing. A cached favicon or stylesheet that survives an edit is time
        # spent wondering why a change did nothing.
        self.send_header("Cache-Control", "no-store")
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
                st = path.stat()
                node["size"] = st.st_size
                # mtime lets the browser tell which files a chat turn touched,
                # by diffing a tree taken before the turn against one after.
                # That is the only signal available: the assistant edits files
                # through its own tools and does not report what it wrote.
                node["mtime"] = int(st.st_mtime)
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
            for label, folder, mode in p.folder_roots:
                path = Path(folder).expanduser()
                roots.append({
                    "label": label,
                    "path": str(path),
                    "mode": mode,
                    "writable": mode == "home",
                    "exists": path.exists(),
                    "tree": self._tree_node(path),
                })
            if not roots:
                if p.source_file:
                    roots.append({
                        "label": "Project file",
                        "path": str(p.source_file),
                        "mode": "store",
                        "writable": False,
                        "exists": Path(p.source_file).exists(),
                        "tree": self._tree_node(Path(p.source_file)),
                    })
                note = ("No home folder set for this project. Use Set home in "
                        "the workbench header to name the directory this "
                        "project works in, or Link folder to point at one for "
                        "reference.")
            return {"generated": date.today().isoformat(),
                    "project": p.id, "roots": roots, "note": note,
                    "home": p.home_folder or ""}

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

    def _linked_roots(self, board: Board) -> list[Path]:
        """Every folder a project points at for reference.

        These are readable and never writable. A link is a pointer, so the
        editor and the importer both refuse to land inside one.
        """
        out: list[Path] = []
        for p in board.load(tuple(board.roots)):
            for _label, folder, mode in p.folder_roots:
                if mode != "linked":
                    continue
                try:
                    out.append(Path(folder).expanduser().resolve())
                except OSError:
                    continue
        return out

    def _refuse_if_linked(self, board: Board, path: Path) -> None:
        for root in self._linked_roots(board):
            if path == root or root in path.parents:
                raise StoreError("that folder is linked for reference and is "
                                 "read-only. Import into the project home "
                                 "instead.")

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

    def _project_root(self, project) -> Path:
        """Where this project writes. The home, or nowhere.

        A linked folder is never a write target, so it is not considered here
        even when it is the only folder the project browses.
        """
        home = project.home_folder
        if home:
            return Path(home).expanduser().resolve()
        if project.source_file is not None:
            return Path(project.source_file).expanduser().resolve().parent
        raise StoreError("this project has no home folder to hold imported "
                         "files. Set home first.")

    def _unique_path(self, path: Path) -> Path:
        if not path.exists():
            return path
        base = path.parent
        stem = path.stem
        suffix = "".join(path.suffixes) or path.suffix
        n = 2
        while True:
            candidate = base / f"{stem}-{n}{suffix}"
            if not candidate.exists():
                return candidate
            n += 1

    def _import_target(self, root: Path, rel: str, task_id: str = "") -> Path:
        rel = str(rel or "").strip().replace("\\", "/")
        if not rel:
            raise StoreError("no filename given")
        rel_path = Path(rel)
        if rel_path.is_absolute() or any(part == ".." for part in rel_path.parts):
            raise StoreError("import path must stay inside the project")
        base = (root / "files" / "tasks" / task_id) if task_id else (root / "files" / "project")
        target = (base / rel_path).resolve()
        try:
            target.relative_to(root)
        except ValueError as e:
            raise StoreError("import path escaped the project folder") from e
        target.parent.mkdir(parents=True, exist_ok=True)
        return self._unique_path(target)

    def _copy_imports(self, project, files, task_id: str = ""):
        root_dir = self._project_root(project)
        imported = []
        for item in files:
            rel = str(item.get("rel") or item.get("name") or "").strip()
            target = self._import_target(root_dir, rel, task_id)
            if item.get("data_b64"):
                try:
                    blob = base64.b64decode(item["data_b64"], validate=True)
                except (ValueError, binascii.Error) as e:
                    raise StoreError(str(e)) from e
                target.write_bytes(blob)
            elif item.get("text") is not None:
                target.write_text(str(item.get("text")), encoding="utf-8")
            else:
                raise StoreError("file had no content")
            if task_id:
                edits.add_task_file(project, task_id, {"path": str(target)})
            imported.append(str(target))
        if task_id:
            save(project)
        return imported

    def _remove_imported_file(self, board, project, target: str, task_id: str = ""):
        path, _root = self._resolve_in_roots(board, target)
        if path.exists() and path.is_dir():
            raise StoreError("that path is a folder, not a file")
        if path.exists():
            path.unlink()
        if task_id:
            edits.remove_task_file(project, task_id, {"path": str(path)})
        else:
            for t in project.tasks:
                try:
                    edits.remove_task_file(project, t.id, {"path": str(path)})
                except EditError:
                    pass
        save(project)
        return str(path)

    def _carry(self, board, store, data: dict):
        """Give a carry-forward item one of three exits.

        A standing list that only grows is read once and skipped after that, so
        every item here leaves by becoming a task on a project, becoming a
        project of its own, or being dropped with a reason. All three archive
        the original text; none of them lose it.

        The store edit happens before the item is removed. If adding the task
        fails, the item is still on the list, which is the recoverable order.
        """
        action = str(data.get("action", "")).strip()
        item = data.get("item", "")
        if isinstance(item, dict):
            item_id = str(item.get("id", "")).strip()
        else:
            item_id = str(item).strip()
        if not item_id:
            return self._json({"error": "no carry-forward item given"}, 400)

        try:
            item = carrymod.get(item_id)
        except CarryError as e:
            return self._json({"error": str(e)}, 400)

        try:
            projects = board.load((store,))
        except StoreError as e:
            return self._json({"error": str(e)}, 400)

        created = {}
        try:
            if action == "task":
                target = next((x for x in projects
                               if x.id == data.get("project")), None)
                if target is None:
                    return self._json({"error": "no such project in that store"}, 404)
                fields = dict(data.get("fields") or {})
                fields.setdefault("title", item["title"])
                # The detail is the reasoning that made it worth carrying. It
                # belongs on the task, or the task is a title with no why.
                fields.setdefault("note", item["detail"] or item["text"])
                if item["due"]:
                    fields.setdefault("due", item["due"])
                task = edits.add_task(target, fields)
                save(target)
                created = {"project": target.id, "task": task.id,
                           "title": task.title}
                note = f"{target.id}:{task.id}"
            elif action == "project":
                fields = dict(data.get("fields") or {})
                fields.setdefault("name", item["title"])
                fields.setdefault("problem", item["text"])
                fields.setdefault("store", store)
                project = edits.new_project(projects, fields)
                root = board.root_for(store)
                project.source_file = root / f"{project.id}.toml"
                save(project)
                created = {"project": project.id, "name": project.name,
                           "file": str(project.source_file)}
                note = project.id
            elif action == "drop":
                note = str(data.get("reason", "")).strip()
                if not note:
                    return self._json(
                        {"error": "dropping needs a reason, it goes in the archive"}, 400)
            else:
                return self._json({"error": f"unknown action {action!r}"}, 400)
        except (EditError, StoreError) as e:
            return self._json({"error": str(e)}, 400)

        try:
            resolved = carrymod.resolve(item_id, action, note)
        except CarryError as e:
            # The store edit already happened and is not rolled back: a real
            # task that exists is better than a silent revert. Say so plainly.
            return self._json({
                "error": f"{e}. The store change was made: {created or 'none'}.",
            }, 400)

        return self._json({"ok": True, "action": action,
                           "created": created, "resolved": resolved})

    def _morning(self, data: dict):
        """Run the existing start-my-day briefing and report where it landed.

        The script lives in the KaiserKM tool suite, not in this repo, so the
        location is resolved from the environment with that as the default. A
        hardcoded repo-relative path was wrong and silently 404'd.
        """
        script = MORNING_SCRIPT
        if not script.exists():
            return self._json(
                {"error": f"morning briefing script not found at {script}"}, 404)
        cmd = [sys.executable, str(script)]
        projects = str(data.get("projects") or "").strip()
        if projects:
            cmd += ["--projects", projects]
        src_file = None
        try:
            src_file = tempfile.NamedTemporaryFile(
                mode="w+", suffix=".json", prefix="hiveframe-morning-", delete=False
            )
            src_file.close()
            cmd += ["--json-out", src_file.name]
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=MORNING_TIMEOUT_S, cwd=str(script.parent))
        except subprocess.TimeoutExpired:
            return self._json(
                {"error": f"briefing did not finish within {MORNING_TIMEOUT_S}s"}, 400)
        except OSError as e:
            return self._json({"error": f"could not run the briefing: {e}"}, 400)

        stdout, stderr = proc.stdout or "", proc.stderr or ""
        source_data = None
        if src_file is not None:
            try:
                src_path = Path(src_file.name)
                if src_path.exists():
                    source_data = json.loads(src_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                source_data = None
            finally:
                try:
                    src_path.unlink(missing_ok=True)
                except OSError:
                    pass
        # The script announces its own output path on stderr. Trust that over a
        # guess, because --out can send it somewhere else entirely.
        briefing = ""
        for line in stderr.splitlines():
            if "Briefing written:" in line:
                briefing = line.split("Briefing written:", 1)[1].strip()
        if proc.returncode != 0:
            return self._json({
                "error": stderr.strip()[-400:] or "the briefing failed",
                "briefing": briefing,
            }, 400)
        return self._json({
            "ok": True,
            "briefing": briefing,
            "markdown": stdout,
            "data": source_data,
        })

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)

        if u.path in ("/", "/index.html"):
            return self._file(WEB / "index.html")

        # Browsers ask for /favicon.ico on their own, whatever the page links
        # to. Answering that request with the SVG is better than a 404: a
        # browser that got a 404 once will keep showing the blank page icon.
        if u.path in ("/favicon.svg", "/favicon.ico"):
            return self._file(WEB / "favicon.svg")


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

        if u.path == "/api/pickfolder":
            # A native folder chooser, because the browser has none. An
            # <input webkitdirectory> is an upload control: it enumerates every
            # file in the folder and never reveals an absolute path, which is
            # the one thing naming a folder requires. The server is local, so it
            # can ask macOS instead. This only reads a path back; nothing is
            # opened, moved or copied.
            prompt = q.get("prompt", ["Choose a folder"])[0]
            start = q.get("start", [""])[0]
            script = ('set theFolder to choose folder with prompt "'
                      + prompt.replace('"', "'") + '"')
            if start:
                sp = Path(start).expanduser()
                if sp.is_dir():
                    script += ' default location POSIX file "' + str(sp) + '"'
            script += "\nPOSIX path of theFolder"
            try:
                r = subprocess.run(["/usr/bin/osascript", "-e", script],
                                   capture_output=True, text=True, timeout=300)
            except subprocess.TimeoutExpired:
                return self._json({"ok": False, "error": "the folder chooser timed out"}, 400)
            path = (r.stdout or "").strip().rstrip("/")
            if r.returncode != 0 or not path:
                # Cancelling is a normal outcome, not an error to shout about.
                return self._json({"ok": False, "cancelled": True})
            return self._json({"ok": True, "path": path})

        if u.path == "/api/carry":
            try:
                items = carrymod.parse()
            except CarryError as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"items": items, "path": str(carrymod.CARRY_PATH)})

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

        # ---- Confluence, read only ----------------------------------
        # Three GETs against the system of record. The client module has no
        # write verb at all, so nothing typed here can change a page.

        if u.path == "/api/confluence/state":
            check = q.get("check", ["0"])[0] not in ("0", "", "false")
            return self._json(confmod.state(check=check))

        if u.path == "/api/confluence/search":
            try:
                rows = confmod.search(q.get("q", [""])[0],
                                      q.get("space", [""])[0],
                                      int(q.get("limit", ["15"])[0] or 15))
            except (ConfluenceError, ValueError) as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"base": confmod.BASE, "results": rows})

        if u.path == "/api/confluence/page":
            try:
                return self._json(confmod.page(q.get("id", [""])[0]))
            except ConfluenceError as e:
                return self._json({"error": str(e)}, 400)

        if u.path == "/api/confluence/spaces":
            try:
                return self._json({"spaces": confmod.spaces()})
            except ConfluenceError as e:
                return self._json({"error": str(e)}, 400)

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
            try:
                self._refuse_if_linked(board, path)
            except StoreError as e:
                return self._json({"error": str(e)}, 400)
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

        if u.path == "/api/carry":
            return self._carry(board, store, data)

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

        if u.path == "/api/chat/clear":
            # Ends the thread. The next turn is a first turn and pays for
            # nothing that came before it.
            res = chatmod.clear_session(root, data.get("project", ""))
            return self._json({"ok": True, **res})

        if u.path == "/api/morning":
            return self._morning(data)

        self._json({"error": "not found"}, 404)

    def _chat_dirs(self, board, store, root, project_id=""):
        dirs = [root]
        repo = Path(__file__).resolve().parent.parent
        if repo not in dirs:
            dirs.append(repo)
        if project_id:
            wanted = next((p for p in board.load((store,)) if p.id == project_id), None)
            if wanted is not None:
                for _label, folder in wanted.folders:
                    try:
                        path = Path(folder).expanduser().resolve()
                    except OSError:
                        continue
                    if path not in dirs:
                        dirs.append(path)
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
                                         dirs=self._chat_dirs(board, store, root, project),
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
                                 dirs=self._chat_dirs(board, store, root, project),
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
            elif action in {
                "project", "charter", "task.add", "task.edit", "task.drop",
                "task.reopen",
                "artifact.add", "file.import", "project.file.add",
                "project.file.remove", "task.file.add", "task.file.remove",
                "file.remove", "relation.add", "relation.verdict", "uses",
            }:
                # Older clients and cached pages have sent project-edit actions
                # to the tool endpoint. Treat those as project edits so a stale
                # browser does not turn a valid import into an unknown action.
                return self._edit(board, store, data)
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
            elif action == "task.reopen":
                edits.reopen_task(p, data.get("task", ""), data.get("reason", ""))
            elif action == "artifact.add":
                edits.add_artifact(p, payload)
            elif action == "project.home.set":
                edits.set_home(p, payload or data)
            elif action == "project.home.clear":
                edits.clear_home(p)
            elif action == "folder.link":
                edits.link_folder(p, payload or data)
            elif action == "folder.unlink":
                edits.unlink_folder(p, payload or data)
            elif action in ("project.file.add", "file.import"):
                files = data.get("files") or payload.get("files") or []
                if not files:
                    return self._json({"error": "no files given"}, 400)
                try:
                    imported = self._copy_imports(p, files)
                except StoreError as e:
                    return self._json({"error": str(e)}, 400)
                return self._json({"ok": True, "project": p.id, "action": action, "imported": imported})
            elif action in ("project.file.remove", "file.remove"):
                try:
                    removed = self._remove_imported_file(board, p, data.get("path", ""))
                except StoreError as e:
                    return self._json({"error": str(e)}, 400)
                return self._json({"ok": True, "project": p.id, "action": action, "removed": removed})
            elif action == "task.file.add":
                files = data.get("files") or payload.get("files") or []
                if files:
                    task_id = data.get("task", "")
                    if not task_id:
                        return self._json({"error": "no task given"}, 400)
                    try:
                        imported = self._copy_imports(p, files, task_id)
                    except StoreError as e:
                        return self._json({"error": str(e)}, 400)
                    return self._json({"ok": True, "project": p.id, "action": action, "imported": imported})
                edits.add_task_file(p, data.get("task", ""), payload)
            elif action == "task.file.remove":
                try:
                    removed = self._remove_imported_file(board, p, data.get("path", ""), data.get("task", ""))
                except StoreError as e:
                    return self._json({"error": str(e)}, 400)
                return self._json({"ok": True, "project": p.id, "action": action, "removed": removed})
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

    problems = board.check()
    if problems:
        for line in problems:
            print(f"  FAIL {line}")
        return 1
    print("  every configured store root exists")

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

    # The favicon is XML. A browser refuses a malformed one silently, and the
    # server still answers 200, so only a parse proves it will render.
    import xml.etree.ElementTree as _ET
    _ico = WEB / "favicon.svg"
    if not _ico.exists():
        print("  FAIL: web/favicon.svg is missing")
        return 1
    try:
        _ET.parse(_ico)
    except _ET.ParseError as exc:
        print(f"  FAIL: web/favicon.svg is not well-formed XML: {exc}")
        return 1
    print("  favicon.svg parses as XML")

    # The markdown renderer walks lines with a manual index, so any branch that
    # can decline a line without advancing that index locks the browser tab
    # solid: Chrome shows "page unresponsive" and the only fix is to kill it.
    # That happened once already, with a line starting with a pipe that had no
    # separator row under it, which is every table for as long as it is still
    # streaming in. Node is not assumed to be installed, so rather than execute
    # the renderer this reads it: the paragraph branch is the last resort, and
    # it must carry an unconditional advance for the case where it matched
    # nothing. This is a smoke alarm, not a proof.
    _idx = (WEB / "index.html").read_text(encoding="utf-8")
    _at = _idx.find("function md(src)")
    if _at < 0:
        print("  FAIL: md() not found in index.html")
        return 1
    _body = _idx[_at:_at + 4000]
    if "if (!para.length) para.push(lines[i++]);" not in _body:
        print("  FAIL: md() paragraph branch can decline a line without "
              "advancing i; a streaming table will hang the tab")
        return 1
    print("  md() always consumes a line, so a partial table cannot hang the tab")

    # A block must not demote a project that still has a move available.
    #
    # The probe has to be a project the scorer actually ranks. Some kinds are
    # exempt on purpose: routine running work scores a flat 0 whatever its
    # status, so blocking it changes nothing and the comparison below reads
    # that as a failure. This once picked projects[0] and broke the moment a
    # routine project sorted first alphabetically.
    probe_src = next((p for p in projects
                      if p.actionable_tasks and score(p)[0] > 0), None)
    if probe_src is None:
        print("  skipped: no ranked project with an available move to probe")
    else:
        probe = replace(probe_src, status="blocked")
        if score(probe)[0] <= score(probe_src)[0]:
            print(f"  FAIL: blocking {probe_src.id}, which has an available "
                  f"move, did not raise its rank")
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

    # The CLI reports credits as a running session total. If this ever logs the
    # raw reading again, every long thread reports a per-turn price it did not
    # charge, and the cost picture is quietly wrong rather than loudly broken.
    with tempfile.TemporaryDirectory() as td:
        mroot = Path(td)
        a = chatmod.meter_turn(mroot, "p", "sess-1", 10.0)
        assert (a["credits"], a["credits_basis"], a["depth"]) == (10.0, "first", 1), a
        b = chatmod.meter_turn(mroot, "p", "sess-1", 34.0)
        assert (b["credits"], b["credits_basis"], b["depth"]) == (24.0, "delta", 2), b
        assert b["credits_total"] == 34.0, b
        # A reading below the last one is a different odometer. No negative price.
        c = chatmod.meter_turn(mroot, "p", "sess-1", 4.0)
        assert c["credits"] is None and c["credits_basis"] == "reset", c
        # Clearing drops the meter, so the next thread does not diff against a
        # total it never ran up.
        chatmod.clear_session(mroot, "p")
        assert chatmod.meter_read(mroot, "p") == {}, "clear must reset the meter"
        d = chatmod.meter_turn(mroot, "p", "sess-2", 7.0)
        assert (d["credits"], d["credits_basis"], d["depth"]) == (7.0, "first", 1), d
    print("  credits are logged per turn, not as the session odometer")

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

    # Refuse to serve a board we cannot read. A missing store root used to be
    # skipped, so the server answered 200 with zero projects and it looked like
    # the data was gone. Say which path is wrong, and say it before binding.
    try:
        problems = Board.from_env().check()
    except StoreError as e:
        print(f"store configuration error: {e}", file=sys.stderr)
        return 2
    if problems:
        for line in problems:
            print(f"store configuration error: {line}", file=sys.stderr)
        print("Not starting. An empty board and a wrong path look identical "
              "once served.", file=sys.stderr)
        return 2

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
